from router_service.schemas import InternalPrepareRequest, InternalRouteRequest, RuntimeContext


def test_internal_route_request_carries_runtime_context():
    req = InternalRouteRequest(
        tenant_id="corp",
        user_id="u-1",
        session_id="s-1",
        request_id="r-1",
        message="hello",
        runtime_context=RuntimeContext(
            tenant_id="corp",
            user_id="u-1",
            session_id="s-1",
            state_service_url="http://state-service:8006",
            state_token="token",
        ),
    )

    assert req.runtime_context is not None
    assert req.runtime_context.tenant_id == "corp"
    assert req.runtime_context.session_id == "s-1"


def test_prepare_request_marks_stateless_runtime():
    req = InternalPrepareRequest(
        user_id="u-1",
        hermes_home_path="/tmp/hermes-runtime/s-1",
        stateless=True,
        runtime_context=RuntimeContext(tenant_id="corp", user_id="u-1", session_id="s-1"),
    )

    assert req.stateless is True
    assert req.runtime_context.user_id == "u-1"
