from src.container import initialize_data


def test_initialization_seeds_and_preserves_data(tmp_path, monkeypatch):
    source = tmp_path / "app"
    data = tmp_path / "data"
    (source / "examples").mkdir(parents=True)
    (source / "docs").mkdir()
    (source / "examples/content-plan.yaml").write_text("posts: []\n")
    (source / "docs/notes.md").write_text("Initial docs")
    monkeypatch.setattr("src.container.APP_DIR", source)
    monkeypatch.setattr("src.container.DATA_DIR", data)
    initialize_data()
    assert (data / "content-plan.yaml").read_text() == "posts: []\n"
    assert (data / "out/drafts").is_dir()
    assert (data / "out/images").is_dir()
    (data / "content-plan.yaml").write_text("User plan")
    (data / "docs/notes.md").write_text("User docs")
    initialize_data()
    assert (data / "content-plan.yaml").read_text() == "User plan"
    assert (data / "docs/notes.md").read_text() == "User docs"
