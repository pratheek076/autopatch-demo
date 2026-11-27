import httpx

from src.autopatch.integrations.jenkins import JenkinsClient


def test_failed_stage_fallback_uses_recent_console_output(monkeypatch):
    log = (
        "dependency installation output\n" * 2000
        + "[Pipeline] stage\n"
        + "[Pipeline] { (Test)\n"
        + "[Pipeline] // stage\n"
        + "[Pipeline] stage\n"
        + "[Pipeline] { (Declarative: Post Actions)\n"
        + "java.lang.NoSuchMethodError: No such DSL method 'coberturaAdapter'\n"
    )
    client = JenkinsClient()

    def fake_get(path):
        request = httpx.Request("GET", f"http://jenkins{path}")
        if path.endswith("/wfapi/describe"):
            httpx.Response(404, request=request).raise_for_status()
        return httpx.Response(200, text=log, request=request)

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_failed_stage("autopatch-sample", 17) == "Declarative: Post Actions"
