import requests
import os


def get_person_urn(token: str) -> str:
    """Fetch person URN from LinkedIn OIDC userinfo."""
    r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Could not fetch LinkedIn identity ({r.status_code}): {r.text}")
    sub = r.json().get("sub")
    if not sub:
        raise RuntimeError("LinkedIn userinfo did not return a subject ID.")
    return f"urn:li:person:{sub}"


def upload_image_to_linkedin(token: str, person_urn: str, image_bytes: bytes) -> str:
    """Upload image to LinkedIn and return the asset URN."""
    # Step 1: Register upload
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent",
                }
            ],
        }
    }
    reg_resp = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=register_payload,
        timeout=15,
    )
    if reg_resp.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn register upload failed ({reg_resp.status_code}): {reg_resp.text}")

    reg_data = reg_resp.json()
    upload_url = (
        reg_data["value"]["uploadMechanism"]
        ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
        ["uploadUrl"]
    )
    asset_urn = reg_data["value"]["asset"]

    # Step 2: Upload image bytes
    up_resp = requests.put(
        upload_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/jpeg",
        },
        data=image_bytes,
        timeout=30,
    )
    if up_resp.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn image upload failed ({up_resp.status_code}): {up_resp.text}")

    return asset_urn


def publish_to_linkedin(post_content: str, image_bytes: bytes = None) -> None:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN secret is not set.")

    person_urn = get_person_urn(token)
    print(f"Using person URN: {person_urn}")

    if image_bytes:
        asset_urn = upload_image_to_linkedin(token, person_urn, image_bytes)
        share_content = {
            "shareCommentary": {"text": post_content},
            "shareMediaCategory": "IMAGE",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": ""},
                    "media": asset_urn,
                    "title": {"text": ""},
                }
            ],
        }
    else:
        share_content = {
            "shareCommentary": {"text": post_content},
            "shareMediaCategory": "NONE",
        }

    post_data = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content,
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    response = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=post_data,
        timeout=15,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"LinkedIn API error ({response.status_code}): {response.text}"
        )

    post_id = response.json().get("id", "unknown")
    label = "with image" if image_bytes else "text-only"
    print(f"Post published to LinkedIn ({label})! ID: {post_id}")


if __name__ == "__main__":
    with open("post.txt", "r", encoding="utf-8") as f:
        content = f.read()
    publish_to_linkedin(content)
