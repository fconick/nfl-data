from nfl_data.config import addressing_style_for, infer_region


def test_backblaze_uses_virtual_and_endpoint_region() -> None:
    endpoint = "https://s3.us-east-005.backblazeb2.com"
    assert addressing_style_for(endpoint) == "virtual"
    assert infer_region("us-east-1", endpoint) == "us-east-005"


def test_minio_uses_path() -> None:
    assert addressing_style_for("http://localhost:9000") == "path"


def test_override_wins() -> None:
    assert addressing_style_for("https://s3.us-east-005.backblazeb2.com", "path") == "path"
