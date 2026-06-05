import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_version

def test_manifest_version_matches(tmp_path):
    yml = tmp_path / "restash.yml"
    yml.write_text("name: Restash\nversion: 1.2.3\n")
    assert check_version.manifest_version(yml) == "1.2.3"

def test_matches_tag_true_false():
    assert check_version.matches("1.2.3", "v1.2.3") is True
    assert check_version.matches("1.2.3", "1.2.3") is True
    assert check_version.matches("1.2.3", "v1.2.4") is False
