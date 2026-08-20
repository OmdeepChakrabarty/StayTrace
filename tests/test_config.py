import json
from pathlib import Path


def test_mock_data_valid_json():
    mock_data_path = Path(__file__).parent / "mock_data.json"
    assert mock_data_path.exists(), "mock_data.json must exist"
    
    with open(mock_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert "carriers" in data
    assert "raw_parcels" in data
    assert "tracking_numbers" in data
    assert "carrier_aliases" in data
    assert "status_mappings" in data
    assert isinstance(data["carriers"], list)
    assert len(data["carriers"]) > 0


def test_requirements_file_exists():
    req_path = Path(__file__).parent.parent / "requirements.txt"
    assert req_path.exists()
    content = req_path.read_text(encoding="utf-8")
    assert "pytest" in content
    assert "requests" in content


def test_env_example_file_exists():
    env_path = Path(__file__).parent.parent / ".env.example"
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    assert "BRIGHTDATA" in content
    assert "DATABASE_PATH" in content


def test_agents_md_exists():
    agents_path = Path(__file__).parent.parent / "AGENTS.md"
    assert agents_path.exists()
    content = agents_path.read_text(encoding="utf-8")
    assert "ParcelPulse" in content
    assert "Level 0" in content
    assert "Level 1" in content
