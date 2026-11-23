"""Money safety: the ledger and the Higgsfield client, with a fake HTTP transport."""
import json

import httpx
import pytest

from reels import config
from reels.higgsfield import CliProvider, ProviderError, RestProvider, cli_request, price
from reels.ledger import Ledger, MoneyError

KEY = "id123:secret456"
RATES = ("Standard self-serve rates in USD per second of generated video. - Without video input: 480p: $0.1177; 720p: $0.2647; 1080p: $0.6518. "
         "- With video input: 480p: $0.1387; 720p: $0.3264; 1080p: $0.7858. Total price = selected rate × output duration in seconds.")


def test_ledger_caps_and_releases(tmp_path):
    ledger = Ledger(tmp_path / "l.sqlite")
    with pytest.raises(MoneyError, match="No approved"):
        ledger.reserve("ep", "draft", "c01/t1", "video", "m", {}, "1.00", "takes/c01/t1.mp4")
    with pytest.raises(MoneyError, match="own words"):
        ledger.approve("ep", "draft", "2.60", " ")
    ledger.approve("ep", "draft", "2.60", "批", base="2.00")
    first = ledger.reserve("ep", "draft", "c01/t1", "video", "m", {"a": 1}, "1.00", "takes/c01/t1.mp4")
    with pytest.raises(MoneyError, match="already in flight"):
        ledger.reserve("ep", "draft", "c01/t1", "video", "m", {}, "1.00", "x")
    ledger.accepted(first["id"], "req-1", "https://api.higgsfield.ai/requests/req-1/status")
    ledger.finish(first["id"], "completed", outputs=["u"])
    second = ledger.reserve("ep", "draft", "c01/t2", "video", "m", {}, "1.00", "x")
    ledger.finish(second["id"], "failed", error="Generation failed")  # failed jobs are not charged: money comes back
    third = ledger.reserve("ep", "draft", "c01/t3", "video", "m", {}, "1.50", "x")
    ledger.unknown(third["id"])  # unknown outcome keeps its hold
    with pytest.raises(MoneyError, match="Stop and ask the user"):
        ledger.reserve("ep", "draft", "c01/t4", "video", "m", {}, "0.20", "x")
    summary = ledger.summary("ep")["draft"]
    assert summary["used"] == "2.50" and summary["into_retake_allowance"] is True
    assert ledger.summary("ep")["final"]["approved"] is False


def test_price_reads_both_answer_shapes():
    assert price({"usd": "0.054"}, {}) == "0.054"
    card = {"type": "description", "pricing_description": RATES}
    assert float(price(card, {"draft": True, "duration": 8, "resolution": "1080p"})) == pytest.approx(0.9416)
    assert float(price(card, {"duration": 7, "resolution": "1080p"})) == pytest.approx(4.5626)
    assert float(price(card, {"duration": 5, "resolution": "720p", "video_urls": ["x"]})) == pytest.approx(1.632)
    with pytest.raises(ProviderError, match="no exact price"):
        price({"type": "description", "pricing_description": "Contact sales."}, {})


def client(handler):
    return RestProvider(KEY, transport=httpx.MockTransport(handler), sleep=lambda _: None)


def test_client_submits_with_idempotency_and_reads_status():
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.path.startswith("/estimate/"):
            return httpx.Response(200, json={"type": "description", "pricing_description": RATES})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "completed", "request_id": "r1", "video": {"url": "https://d3u0tzju9qaucj.cloudfront.net/out.mp4"}})
        return httpx.Response(200, json={"status": "queued", "request_id": "r1", "status_url": "https://api.higgsfield.ai/requests/r1/status"})
    provider = client(handler)
    body = {"prompt": "p", "image_urls": ["https://d3snorpfx4xhv8.cloudfront.net/a.png"], "duration": 6, "draft": True}
    assert float(provider.estimate(config.VIDEO, body)) == pytest.approx(0.7062)
    identity = provider.submit(config.VIDEO, body, "idem-1")
    assert identity == {"request_id": "r1", "status_url": "https://api.higgsfield.ai/requests/r1/status"}
    assert provider.status(identity["status_url"])["outputs"] == ["https://d3u0tzju9qaucj.cloudfront.net/out.mp4"]
    submit = seen[1]
    assert submit.url.path == "/" + config.VIDEO and submit.headers["Idempotency-Key"] == "idem-1"
    assert submit.headers["Authorization"] == f"Key {KEY}" and json.loads(submit.content) == body


def test_key_never_leaves_the_api_host(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host == "api.higgsfield.ai":
            return httpx.Response(200, json={"upload_url": "https://bucket.s3.amazonaws.com/put?sig=1", "public_url": "https://d3snorpfx4xhv8.cloudfront.net/in.png",
                                             "upload_headers": {"Content-Type": "image/png"}})
        return httpx.Response(200)
    provider = client(handler)
    picture = tmp_path / "a.png"
    picture.write_bytes(b"png")
    assert provider.upload(picture) == "https://d3snorpfx4xhv8.cloudfront.net/in.png"
    assert "Authorization" in seen[0].headers and "authorization" not in seen[1].headers
    with pytest.raises(ProviderError, match="anywhere but"):
        provider._api("GET", "https://evil.example/requests/1/status")
    with pytest.raises(ProviderError, match="not seen before"):
        provider.download("https://evil.example.net/x.mp4", tmp_path / "x.mp4")


def test_a_refused_request_is_safe_but_a_server_error_is_unknown():
    refused = client(lambda request: httpx.Response(422, json={"detail": "duration must be >= 4"}))
    with pytest.raises(ProviderError) as error:
        refused.submit(config.VIDEO, {}, "k")
    assert error.value.unknown is False and "duration must be" in str(error.value)
    calls = []
    def broken(request):
        calls.append(request)
        return httpx.Response(503)
    with pytest.raises(ProviderError) as error:
        client(broken).submit(config.VIDEO, {}, "k")
    assert error.value.unknown is True and len(calls) == 1  # a POST is never retried automatically


def test_720p_plan_has_no_1080p_pass():
    from reels.checks import plan_cost
    cost = plan_cost(15, 2, 2, 1, takes=1, quality="720p", unit="US$")
    assert cost["final"] == "0.00" and cost["draft"] == "3.98"
    credits = plan_cost(15, 2, 2, 1, takes=1, quality="720p")
    assert credits["unit"] == "credits" and credits["draft"] == "105.00"  # 7 credits a second at 720p


# ---- the Higgsfield CLI route ------------------------------------------------------------
def test_cli_request_translates_the_engine_shapes():
    body = {"prompt": "p", "image_urls": ["img-1", "img-2"], "audio_urls": ["aud-1"], "duration": 6, "aspect_ratio": "9:16", "generate_audio": True, "draft": True}
    job, args = cli_request(config.VIDEO, body)
    assert job == config.CLI_VIDEO
    assert args[:2] == ["--mode", "omni_reference"] and ["--draft", "true"] == args[args.index("--draft"):args.index("--draft") + 2]
    assert args[args.index("--resolution") + 1] == "480p" and args.count("--image-references") == 2 and args.count("--audio-references") == 1
    assert args[args.index("--generate_audio") + 1] == "true"
    job, args = cli_request(config.VIDEO_TEXT, {"prompt": "p", "duration": 5, "draft": True})
    assert args[:2] == ["--mode", "t2v"]
    job, args = cli_request(config.IMAGE_EDIT, {"prompt": "p", "image_urls": ["a"], "resolution": "1.5k", "aspect_ratio": "3:4"})
    assert job == config.CLI_IMAGE and args[-2:] == ["--image-references", "a"]
    job, args = cli_request(config.VIDEO_FINALIZE, {"draft_id": "job-9", "resolution": "1080p"}, {"source_body": body})
    assert "--draft" not in args and args[args.index("--resolution") + 1] == "1080p" and args[-2:] == ["--draft_job_id", "job-9"]
    with pytest.raises(ProviderError, match="original request"):
        cli_request(config.VIDEO_FINALIZE, {"draft_id": "x"})


def fake_cli(answers):
    calls = []
    def run(args):
        calls.append(args)
        for prefix, answer in answers.items():
            if " ".join(args).startswith(prefix):
                return answer
        return 1, "", "Error: unexpected command"
    return run, calls


def test_cli_provider_quotes_submits_and_collects(tmp_path):
    run, calls = fake_cli({
        "generate cost": (0, json.dumps({"credits": 18}), ""),
        "upload create": (0, json.dumps({"id": "up-1", "type": "image", "url": "https://d2ol7oe51mr4n9.cloudfront.net/u/up-1.png"}), ""),
        "generate create": (0, json.dumps({"job_set_id": "set-1", "jobs": [{"id": "job-1", "status": "queued"}]}), ""),
        "generate get": (0, json.dumps({"id": "job-1", "status": "completed", "thumbnail_url": "https://d2ol7oe51mr4n9.cloudfront.net/t.jpg",
                                         "results": [{"url": "https://d2ol7oe51mr4n9.cloudfront.net/out.mp4"}]}), ""),
    })
    provider = CliProvider(run)
    picture = tmp_path / "a.png"
    picture.write_bytes(b"png")
    body = {"prompt": "p", "image_urls": [provider.upload(picture)], "duration": 6, "draft": True}
    assert provider.estimate(config.VIDEO, body) == "18"
    identity = provider.submit(config.VIDEO, body, "idem")
    assert identity == {"request_id": "job-1", "status_url": "higgsfield-cli:job-1"}
    assert provider.status(identity["status_url"]) == {"status": "completed", "outputs": ["https://d2ol7oe51mr4n9.cloudfront.net/out.mp4"], "error": None}
    assert calls[2][:3] == ["generate", "create", config.CLI_VIDEO]


def test_cli_provider_explains_login_plan_and_unknown_outcomes():
    run, _ = fake_cli({"account status": (1, "", "Error: Not authenticated. Run higgsfield auth login")})
    with pytest.raises(ProviderError, match="higgsfield auth login"):
        CliProvider(run).account()
    run, _ = fake_cli({"generate create": (1, "", 'Error: {"error_type":"job_minimum_basic_plan_required"}')})
    with pytest.raises(ProviderError, match="Plus or above") as error:
        CliProvider(run).submit(config.VIDEO, {"prompt": "p", "duration": 5}, "k")
    assert error.value.unknown is False
    run, _ = fake_cli({"generate create": (2, "", "panic: connection reset")})
    with pytest.raises(ProviderError) as error:
        CliProvider(run).submit(config.VIDEO, {"prompt": "p", "duration": 5}, "k")
    assert error.value.unknown is True  # it may have gone through: keep the money held, never resubmit blindly
    run, _ = fake_cli({"generate get": (0, json.dumps({"id": "j", "status": "nsfw"}), "")})
    assert CliProvider(run).status("higgsfield-cli:j")["status"] == "nsfw"
