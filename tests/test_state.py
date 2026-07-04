from graider.models import InviteStatus, MemberState, ProjectState, SetupState
from graider.state import load_state, save_state


def test_missing_returns_empty(tmp_path):
    assert load_state(tmp_path / "none.json").projects == {}


def test_round_trip(tmp_path):
    state = SetupState(
        gitlab_url="https://gl",
        org="swe/2026",
        projects={
            "1": ProjectState(
                group_number="1",
                name="brave-otter",
                project_id=7,
                web_url="https://gl/swe/brave-otter",
                path_with_namespace="swe/brave-otter",
                template="python",
                members=[MemberState(email="a@x.edu", status=InviteStatus.INVITED)],
            )
        },
    )
    path = tmp_path / "graider.lock.json"
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.projects["1"].name == "brave-otter"
    assert loaded.projects["1"].members[0].status == InviteStatus.INVITED
