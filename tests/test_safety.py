from husk import Safety, Tool


def _t(risky=False):
    return Tool("run", "", {"type": "object", "properties": {}}, lambda **k: "", risky=risky)


def test_benign_command_is_allowed_without_hitl():
    s = Safety(hitl=lambda prompt: False)  # would reject if consulted
    assert s.approve(_t(), {"command": "ls -la"}) is True


def test_destructive_command_requires_hitl():
    s = Safety(hitl=lambda prompt: False)
    assert s.approve(_t(), {"command": "rm -rf /"}) is False
    assert s.approve(_t(), {"command": "shutdown now"}) is False


def test_risky_tool_flag_requires_hitl():
    assert Safety(hitl=lambda p: True).approve(_t(risky=True), {}) is True
    assert Safety(hitl=lambda p: False).approve(_t(risky=True), {}) is False


def test_allowlist_mode_blocks_everything_else():
    s = Safety(allow=[r"^ls\b"], hitl=lambda prompt: False)
    assert s.approve(_t(), {"command": "ls"}) is True        # matches allowlist
    assert s.approve(_t(), {"command": "cat x"}) is False     # not allowed -> HITL -> reject
