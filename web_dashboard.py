# web_dashboard.py
import os
import json
import threading
import feedparser   
from flask import Flask, render_template_string, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
from collections import Counter
import matplotlib
matplotlib.use('Agg')  # For non-GUI backend
import matplotlib.pyplot as plt
import io
import base64

from linkedin_publish import publish_to_linkedin

# ---------- Queue Functions ----------
QUEUE_FILE = "post_queue.json"
HISTORY_FILE = "post_history.json"
SCHEDULE_FILE = "schedule.json"

def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            return json.load(f)
    return []

def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)

def queue_pop(index=0):
    q = load_queue()
    if not q or index >= len(q):
        return None
    item = q.pop(index)
    save_queue(q)
    return item

def load_history(limit=20):
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            return data[-limit:] if limit else data
    return []

def save_history(entry):
    data = load_history(limit=None)
    data.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r") as f:
            return json.load(f)
    return None

# ---------- Helper to get generate_post dynamically ----------
_generate_post = None
def get_generate_post():
    global _generate_post
    if _generate_post is None:
        import main
        _generate_post = main.generate_post
    return _generate_post


# ---------- Analytics Chart ----------
def generate_post_chart():
    history = load_history(limit=50)
    if not history:
        return None
    
    # Group by date (last 7 days)
    now = datetime.now()
    last_week = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    counts = {day: 0 for day in last_week}
    for entry in history:
        try:
            date_str = entry.get("date", "").split(" ")[0]  # YYYY-MM-DD
            if date_str in counts:
                counts[date_str] += 1
        except:
            pass
    
    days = list(counts.keys())
    values = list(counts.values())
    
    plt.figure(figsize=(8, 4))
    plt.bar(days, values, color='#0a66c2')
    plt.title('Posts per day (last 7 days)')
    plt.xlabel('Date')
    plt.ylabel('Number of posts')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plot_url = base64.b64encode(buf.getvalue()).decode('utf8')
    plt.close()
    return f'<img src="data:image/png;base64,{plot_url}" class="img-fluid">'

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- HTML Templates (embedded for simplicity) ----------
HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
    <h1 class="mb-4">🤖 Bot Dashboard</h1>
    <ul class="nav nav-tabs mb-4">
        <li class="nav-item"><a class="nav-link active" href="/">Queue</a></li>
        <li class="nav-item"><a class="nav-link" href="/history">History</a></li>
        <li class="nav-item"><a class="nav-link" href="/schedule">Schedule</a></li>
        <li class="nav-item"><a class="nav-link" href="/analytics">Analytics</a></li>
    </ul>

    <div class="card mb-4">
        <div class="card-header">📋 Post Queue ({{ queue|length }}/7)</div>
        <div class="card-body">
            {% if queue %}
                <div class="list-group">
                {% for item in queue %}
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>{{ item.topic }}</strong><br>
                                <small>Added: {{ item.added }}</small>
                            </div>
                            <div>
                                <a href="{{ url_for('preview', idx=loop.index0) }}" class="btn btn-sm btn-primary">Preview</a>
                                <a href="{{ url_for('approve', idx=loop.index0) }}" class="btn btn-sm btn-success">Approve</a>
                                <a href="{{ url_for('remove', idx=loop.index0) }}" class="btn btn-sm btn-danger">Remove</a>
                            </div>
                        </div>
                    </div>
                {% endfor %}
                </div>
            {% else %}
                <p class="text-muted">Queue is empty. Add topics via Telegram: /queue add &lt;topic&gt;</p>
            {% endif %}
        </div>
    </div>

    <div class="card">
        <div class="card-header">✍️ Generate & Edit Post</div>
        <div class="card-body">
            <form action="{{ url_for('generate_edit') }}" method="post">
                <div class="mb-3">
                    <label class="form-label">Topic (required)</label>
                    <input type="text" name="topic" class="form-control" placeholder="e.g., Playwright vs Selenium" required>
                </div>
                <button type="submit" class="btn btn-secondary">Generate & Edit</button>
            </form>
        </div>
    </div>
</div>
</body>
</html>
"""

EDIT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Edit Post</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light p-4">
<div class="container">
    <h3>Edit Post: {{ topic }}</h3>
    <form action="{{ url_for('publish_edited') }}" method="post">
        <input type="hidden" name="topic" value="{{ topic }}">
        <div class="mb-3">
            <textarea name="content" rows="10" class="form-control">{{ content }}</textarea>
        </div>
        <button type="submit" class="btn btn-success">Publish to LinkedIn</button>
        <a href="/" class="btn btn-secondary">Cancel</a>
    </form>
</div>
</body>
</html>
"""

HISTORY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Post History</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light p-4">
<div class="container">
    <h3>📜 Post History (last 20)</h3>
    <a href="/" class="btn btn-sm btn-secondary mb-3">← Back to Dashboard</a>
    <div class="list-group">
        {% for entry in history %}
        <div class="list-group-item">
            <div class="d-flex justify-content-between">
                <strong>{{ entry.date }}</strong>
                <span class="badge bg-secondary">{{ entry.topic }}</span>
            </div>
            <p class="mt-2">{{ entry.text[:200] }}{% if entry.text|length > 200 %}...{% endif %}</p>
            <form action="{{ url_for('repost') }}" method="post" class="mt-2">
                <input type="hidden" name="text" value="{{ entry.text }}">
                <input type="hidden" name="topic" value="{{ entry.topic }}">
                <button type="submit" class="btn btn-sm btn-success">Repost</button>
            </form>
        </div>
        {% endfor %}
    </div>
</div>
</body>
</html>
"""

SCHEDULE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Schedule Manager</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light p-4">
<div class="container">
    <h3>⏰ Auto-Post Schedule</h3>
    <a href="/" class="btn btn-sm btn-secondary mb-3">← Back to Dashboard</a>
    {% if schedule %}
        <div class="alert alert-info">Current schedule: Daily at {{ schedule.hour }}:{{ "%02d" % schedule.minute }} UTC</div>
    {% else %}
        <div class="alert alert-warning">No active schedule.</div>
    {% endif %}
    <div class="card">
        <div class="card-header">Set new schedule</div>
        <div class="card-body">
            <form action="{{ url_for('update_schedule') }}" method="post">
                <div class="row">
                    <div class="col-4">
                        <input type="number" name="hour" min="0" max="23" class="form-control" placeholder="Hour (0-23)" required>
                    </div>
                    <div class="col-4">
                        <input type="number" name="minute" min="0" max="59" class="form-control" placeholder="Minute (0-59)" required>
                    </div>
                    <div class="col-4">
                        <button type="submit" class="btn btn-primary">Set Schedule</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    <form action="{{ url_for('unschedule') }}" method="post" class="mt-3">
        <button type="submit" class="btn btn-danger">Remove Schedule</button>
    </form>
</div>
</body>
</html>
"""

ANALYTICS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Analytics</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light p-4">
<div class="container">
    <h3>📊 Analytics</h3>
    <a href="/" class="btn btn-sm btn-secondary mb-3">← Back to Dashboard</a>
    <div class="card mb-4">
        <div class="card-header">Posts per day (last 7 days)</div>
        <div class="card-body">
            {{ chart|safe if chart else "<p>Not enough data yet.</p>" }}
        </div>
    </div>
    <div class="card">
        <div class="card-header">Top Topics</div>
        <div class="card-body">
            <ul>
                {% for topic, count in top_topics %}
                <li>{{ topic }}: {{ count }} post(s)</li>
                {% endfor %}
            </ul>
        </div>
    </div>
</div>
</body>
</html>
"""

# ---------- Routes ----------
@app.route('/')
def index():
    queue = load_queue()
    return render_template_string(HOME_TEMPLATE, queue=queue)

@app.route('/preview/<int:idx>')
def preview(idx):
    queue = load_queue()
    if idx < 0 or idx >= len(queue):
        return "Invalid item", 404
    item = queue[idx]
    generate_post = get_generate_post()
    post_text = generate_post(topic=item['topic'])
    return f"""
    <html>
    <head><title>Preview</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
    <body class="bg-light p-4">
        <div class="container">
            <h3>Preview: {item['topic']}</h3>
            <div class="card p-3 mb-3">
                {post_text.replace(chr(10), '<br>')}
            </div>
            <a href="{url_for('approve', idx=idx)}" class="btn btn-success">Approve & Publish</a>
            <a href="{url_for('index')}" class="btn btn-secondary">Back</a>
        </div>
    </body>
    </html>
    """

@app.route('/approve/<int:idx>')
def approve(idx):
    item = queue_pop(idx)
    if not item:
        return "Item not found", 404
    generate_post = get_generate_post()
    post_text = generate_post(topic=item['topic'])
    try:
        publish_to_linkedin(post_text)
        # Save to history
        save_history({"date": datetime.now().strftime("%Y-%m-%d %H:%M UTC"), "topic": item['topic'], "text": post_text})
        return f"""
        <html><body style="font-family:sans-serif;padding:20px">
        ✅ Published to LinkedIn!<br>
        Post: {post_text[:150]}...<br>
        <a href="/">Go back</a>
        </body></html>
        """
    except Exception as e:
        return f"❌ Failed: {e}"

@app.route('/remove/<int:idx>')
def remove(idx):
    queue_pop(idx)
    return redirect(url_for('index'))

@app.route('/generate_edit', methods=['POST'])
def generate_edit():
    topic = request.form.get('topic', '').strip()
    if not topic:
        return "No topic provided", 400
    generate_post = get_generate_post()
    post_text = generate_post(topic=topic)
    # Store generated content in session? Use hidden fields for simplicity.
    return render_template_string(EDIT_TEMPLATE, topic=topic, content=post_text)

@app.route('/publish_edited', methods=['POST'])
def publish_edited():
    topic = request.form.get('topic', '')
    content = request.form.get('content', '')
    if not content:
        return "No content", 400
    try:
        publish_to_linkedin(content)
        save_history({"date": datetime.now().strftime("%Y-%m-%d %H:%M UTC"), "topic": topic, "text": content})
        return f"""
        <html><body style="padding:20px">
        ✅ Published edited post to LinkedIn!<br>
        <a href="/">Go back</a>
        </body></html>
        """
    except Exception as e:
        return f"❌ Failed to publish: {e}"

@app.route('/history')
def history():
    hist = load_history(20)
    return render_template_string(HISTORY_TEMPLATE, history=hist)

@app.route('/repost', methods=['POST'])
def repost():
    text = request.form.get('text', '')
    topic = request.form.get('topic', '')
    if not text:
        return "No content", 400
    try:
        publish_to_linkedin(text)
        save_history({"date": datetime.now().strftime("%Y-%m-%d %H:%M UTC"), "topic": topic, "text": text})
        return f"""
        <html><body style="padding:20px">
        ✅ Reposted to LinkedIn!<br>
        <a href="/history">Back to History</a>
        </body></html>
        """
    except Exception as e:
        return f"❌ Failed: {e}"

@app.route('/schedule')
def schedule():
    sched = load_schedule()
    return render_template_string(SCHEDULE_TEMPLATE, schedule=sched)

@app.route('/update_schedule', methods=['POST'])
def update_schedule():
    hour = int(request.form.get('hour', 0))
    minute = int(request.form.get('minute', 0))
    # Save schedule to file (same format as main.py expects)
    with open(SCHEDULE_FILE, "w") as f:
        json.dump({"hour": hour, "minute": minute, "chat_id": 0}, f)
    # Also need to update the running job queue? That's dynamic; we'll rely on bot's restart to pick up.
    # For immediate effect, you might need to signal. But for demo, just save file.
    return redirect(url_for('schedule'))

@app.route('/unschedule', methods=['POST'])
def unschedule():
    if os.path.exists(SCHEDULE_FILE):
        os.remove(SCHEDULE_FILE)
    return redirect(url_for('schedule'))

@app.route('/analytics')
def analytics():
    chart_html = generate_post_chart()
    history = load_history(limit=None)
    topics = [entry.get("topic", "unknown") for entry in history if entry.get("topic") not in ("auto", "scheduled", "")]
    top = Counter(topics).most_common(5)
    return render_template_string(ANALYTICS_TEMPLATE, chart=chart_html, top_topics=top)

def run_web():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_web()