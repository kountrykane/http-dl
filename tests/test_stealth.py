"""
Tests for stealth features: User-Agent rotation and header management.
"""

import pytest
from httpdl.stealth import (
    UserAgentRotator,
    HeaderRotator,
    BrowserProfile,
    get_random_headers,
    DESKTOP_USER_AGENTS,
    MOBILE_USER_AGENTS,
    BOT_USER_AGENTS,
    ACCEPT_LANGUAGES,
)


class TestBrowserProfile:
    """Test BrowserProfile dataclass."""

    def test_browser_profile_initialization(self):
        """Test BrowserProfile initializes correctly."""
        profile = BrowserProfile(
            user_agent="Mozilla/5.0 Test",
            accept="text/html",
            accept_language="en-US",
            accept_encoding="gzip",
            connection="keep-alive",
            upgrade_insecure_requests="1",
            sec_fetch_dest="document",
            sec_fetch_mode="navigate",
            sec_fetch_site="none",
            sec_fetch_user="?1",
        )

        assert profile.user_agent == "Mozilla/5.0 Test"
        assert profile.accept == "text/html"
        assert profile.sec_fetch_user == "?1"

    def test_to_headers(self):
        """Test to_headers converts profile to dict."""
        profile = BrowserProfile(
            user_agent="Mozilla/5.0 Test",
            accept="text/html",
            accept_language="en-US",
            accept_encoding="gzip",
            connection="keep-alive",
            upgrade_insecure_requests="1",
            sec_fetch_dest="document",
            sec_fetch_mode="navigate",
            sec_fetch_site="none",
            sec_fetch_user="?1",
        )

        headers = profile.to_headers()

        assert headers["User-Agent"] == "Mozilla/5.0 Test"
        assert headers["Accept"] == "text/html"
        assert headers["Accept-Language"] == "en-US"
        assert headers["Sec-Fetch-User"] == "?1"

    def test_to_headers_without_sec_fetch_user(self):
        """Test to_headers without optional sec_fetch_user."""
        profile = BrowserProfile(
            user_agent="Mozilla/5.0 Firefox",
            accept="text/html",
            accept_language="en-US",
            accept_encoding="gzip",
            connection="keep-alive",
            upgrade_insecure_requests="1",
            sec_fetch_dest="",
            sec_fetch_mode="",
            sec_fetch_site="",
            sec_fetch_user=None,
        )

        headers = profile.to_headers()

        assert "Sec-Fetch-User" not in headers
        assert headers["User-Agent"] == "Mozilla/5.0 Firefox"


class TestUserAgentRotator:
    """Test UserAgentRotator class."""

    def test_initialization_desktop(self):
        """Test UserAgentRotator initializes with desktop mode."""
        rotator = UserAgentRotator(mode="desktop")

        assert rotator.mode == "desktop"
        assert len(rotator._user_agents) > 0
        assert rotator._user_agents == DESKTOP_USER_AGENTS

    def test_initialization_mobile(self):
        """Test UserAgentRotator initializes with mobile mode."""
        rotator = UserAgentRotator(mode="mobile")

        assert rotator.mode == "mobile"
        assert rotator._user_agents == MOBILE_USER_AGENTS

    def test_initialization_bot(self):
        """Test UserAgentRotator initializes with bot mode."""
        rotator = UserAgentRotator(mode="bot")

        assert rotator.mode == "bot"
        assert rotator._user_agents == BOT_USER_AGENTS

    def test_initialization_mixed(self):
        """Test UserAgentRotator initializes with mixed mode."""
        rotator = UserAgentRotator(mode="mixed")

        assert rotator.mode == "mixed"
        assert len(rotator._user_agents) == len(DESKTOP_USER_AGENTS) + len(MOBILE_USER_AGENTS)

    def test_initialization_custom_agents(self):
        """Test UserAgentRotator with custom agents."""
        custom_agents = ["Custom Agent 1", "Custom Agent 2"]
        rotator = UserAgentRotator(mode="desktop", custom_agents=custom_agents)

        assert rotator._user_agents == custom_agents

    def test_initialization_invalid_mode(self):
        """Test UserAgentRotator raises error for invalid mode."""
        with pytest.raises(ValueError, match="Invalid mode"):
            UserAgentRotator(mode="invalid_mode")

    def test_get_random_user_agent(self):
        """Test get_random_user_agent returns valid User-Agent."""
        rotator = UserAgentRotator(mode="desktop")

        user_agent = rotator.get_random_user_agent()

        assert user_agent in DESKTOP_USER_AGENTS
        assert isinstance(user_agent, str)
        assert len(user_agent) > 0

    def test_get_random_user_agent_randomness(self):
        """Test get_random_user_agent produces variety."""
        rotator = UserAgentRotator(mode="desktop")

        # Get 20 User-Agents
        agents = [rotator.get_random_user_agent() for _ in range(20)]

        # Should have at least 2 different agents (probabilistic, but very likely)
        unique_agents = set(agents)
        assert len(unique_agents) >= 2

    def test_rotate_alias(self):
        """Test rotate() is an alias for get_random_user_agent()."""
        rotator = UserAgentRotator(mode="desktop")

        user_agent = rotator.rotate()

        assert user_agent in DESKTOP_USER_AGENTS

    def test_get_random_profile_desktop(self):
        """Test get_random_profile for desktop browser."""
        rotator = UserAgentRotator(mode="desktop")

        profile = rotator.get_random_profile()

        assert isinstance(profile, BrowserProfile)
        assert profile.user_agent in DESKTOP_USER_AGENTS
        assert profile.accept_language in ACCEPT_LANGUAGES
        assert profile.connection == "keep-alive"
        assert profile.upgrade_insecure_requests == "1"

    def test_get_random_profile_chrome_headers(self):
        """Test get_random_profile includes Sec-Fetch-* headers for Chrome."""
        rotator = UserAgentRotator(mode="desktop")

        # Try multiple times to ensure we get a Chrome user agent
        found_chrome = False
        for _ in range(10):
            profile = rotator.get_random_profile()
            if "Chrome" in profile.user_agent:
                assert profile.sec_fetch_dest == "document"
                assert profile.sec_fetch_mode == "navigate"
                assert profile.sec_fetch_site == "none"
                assert profile.sec_fetch_user == "?1"
                found_chrome = True
                break

        assert found_chrome, "Should have found a Chrome User-Agent"

    def test_get_random_profile_firefox_headers(self):
        """Test get_random_profile handles Firefox (no Sec-Fetch-*)."""
        # Use custom Firefox agent to ensure we test it
        firefox_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
        rotator = UserAgentRotator(mode="desktop", custom_agents=[firefox_agent])

        profile = rotator.get_random_profile()

        assert profile.user_agent == firefox_agent
        assert profile.sec_fetch_dest == ""
        assert profile.sec_fetch_mode == ""
        assert profile.sec_fetch_site == ""
        assert profile.sec_fetch_user is None

    def test_get_random_profile_mobile(self):
        """Test get_random_profile for mobile browser."""
        rotator = UserAgentRotator(mode="mobile")

        profile = rotator.get_random_profile()

        assert profile.user_agent in MOBILE_USER_AGENTS
        assert "Mobile" in profile.user_agent or "Android" in profile.user_agent

    def test_get_random_profile_consistency(self):
        """Test get_random_profile produces consistent headers."""
        rotator = UserAgentRotator(mode="desktop")

        profile = rotator.get_random_profile()

        # Check that all required fields are present
        assert profile.user_agent is not None
        assert profile.accept is not None
        assert profile.accept_language is not None
        assert profile.accept_encoding == "gzip, deflate, br"
        assert profile.connection == "keep-alive"


class TestHeaderRotator:
    """Test HeaderRotator class."""

    def test_initialization(self):
        """Test HeaderRotator initializes correctly."""
        rotator = HeaderRotator(mode="desktop")

        assert isinstance(rotator.ua_rotator, UserAgentRotator)
        assert rotator.ua_rotator.mode == "desktop"

    def test_get_session_headers(self):
        """Test get_session_headers returns complete headers."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_session_headers()

        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Accept-Encoding" in headers
        assert "Connection" in headers

    def test_get_session_headers_consistency(self):
        """Test get_session_headers produces valid browser headers."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_session_headers()

        # Verify header values are reasonable
        assert len(headers["User-Agent"]) > 20
        assert "text/html" in headers["Accept"]
        assert "keep-alive" in headers["Connection"]

    def test_get_request_headers_basic(self):
        """Test get_request_headers without optional parameters."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_request_headers()

        assert "User-Agent" in headers
        assert "Referer" not in headers
        assert "Origin" not in headers

    def test_get_request_headers_with_referer(self):
        """Test get_request_headers with referer."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_request_headers(referer="https://example.com")

        assert headers["Referer"] == "https://example.com"

    def test_get_request_headers_with_origin(self):
        """Test get_request_headers with origin."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_request_headers(origin="https://example.com")

        assert headers["Origin"] == "https://example.com"

    def test_get_request_headers_with_both(self):
        """Test get_request_headers with both referer and origin."""
        rotator = HeaderRotator(mode="desktop")

        headers = rotator.get_request_headers(
            referer="https://example.com/page",
            origin="https://example.com"
        )

        assert headers["Referer"] == "https://example.com/page"
        assert headers["Origin"] == "https://example.com"


class TestGetRandomHeaders:
    """Test get_random_headers convenience function."""

    def test_get_random_headers_default(self):
        """Test get_random_headers with default parameters."""
        headers = get_random_headers()

        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers

    def test_get_random_headers_desktop(self):
        """Test get_random_headers with desktop mode."""
        headers = get_random_headers(mode="desktop")

        # User-Agent should be from desktop list
        assert any(ua in headers["User-Agent"] for ua in ["Chrome", "Firefox", "Safari", "Edge"])

    def test_get_random_headers_mobile(self):
        """Test get_random_headers with mobile mode."""
        headers = get_random_headers(mode="mobile")

        # User-Agent should indicate mobile
        user_agent = headers["User-Agent"]
        assert "Mobile" in user_agent or "Android" in user_agent or "iPhone" in user_agent

    def test_get_random_headers_bot(self):
        """Test get_random_headers with bot mode."""
        headers = get_random_headers(mode="bot")

        # User-Agent should indicate bot
        user_agent = headers["User-Agent"]
        assert "bot" in user_agent.lower() or "crawler" in user_agent.lower()

    def test_get_random_headers_with_referer(self):
        """Test get_random_headers with referer parameter."""
        headers = get_random_headers(referer="https://example.com/page")

        assert headers["Referer"] == "https://example.com/page"

    def test_get_random_headers_variety(self):
        """Test get_random_headers produces variety."""
        # Get 10 header sets
        header_sets = [get_random_headers(mode="desktop") for _ in range(10)]

        # Extract User-Agents
        user_agents = [h["User-Agent"] for h in header_sets]

        # Should have at least 2 different User-Agents (probabilistic)
        unique_agents = set(user_agents)
        assert len(unique_agents) >= 2


class TestUserAgentConstants:
    """Test User-Agent constant lists."""

    def test_desktop_user_agents_non_empty(self):
        """Test DESKTOP_USER_AGENTS is populated."""
        assert len(DESKTOP_USER_AGENTS) > 0
        assert all(isinstance(ua, str) for ua in DESKTOP_USER_AGENTS)

    def test_desktop_user_agents_valid(self):
        """Test DESKTOP_USER_AGENTS contains valid strings."""
        for ua in DESKTOP_USER_AGENTS:
            assert len(ua) > 20
            assert "Mozilla" in ua

    def test_mobile_user_agents_non_empty(self):
        """Test MOBILE_USER_AGENTS is populated."""
        assert len(MOBILE_USER_AGENTS) > 0
        assert all(isinstance(ua, str) for ua in MOBILE_USER_AGENTS)

    def test_mobile_user_agents_valid(self):
        """Test MOBILE_USER_AGENTS indicates mobile."""
        for ua in MOBILE_USER_AGENTS:
            assert "Mobile" in ua or "Android" in ua or "iPhone" in ua or "iPad" in ua

    def test_bot_user_agents_non_empty(self):
        """Test BOT_USER_AGENTS is populated."""
        assert len(BOT_USER_AGENTS) > 0
        assert all(isinstance(ua, str) for ua in BOT_USER_AGENTS)

    def test_bot_user_agents_valid(self):
        """Test BOT_USER_AGENTS indicates bots."""
        for ua in BOT_USER_AGENTS:
            assert "bot" in ua.lower() or "crawler" in ua.lower() or "compatible" in ua.lower()

    def test_accept_languages_non_empty(self):
        """Test ACCEPT_LANGUAGES is populated."""
        assert len(ACCEPT_LANGUAGES) > 0
        assert all(isinstance(lang, str) for lang in ACCEPT_LANGUAGES)

    def test_accept_languages_valid_format(self):
        """Test ACCEPT_LANGUAGES contains valid language strings."""
        for lang in ACCEPT_LANGUAGES:
            assert "en" in lang
            assert "q=" in lang or lang == "en-US" or lang == "en-GB"
