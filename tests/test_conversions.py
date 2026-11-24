# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for conversion reporting (no bench): which CRM Leads count as a website lead, and the pending-event
cookie's format (the same as the wp-conversion-tracking plugin's)."""

import base64
import json

import pytest

from public_site_router import conversions

LEAD = {
	"public_site": "zephyrex.ca",
	"source": "Website",
	"web_form": "contact-zephyrex-ca",
	"email": "a@b.ca",
}


class TestCountsAsLead:
	def test_a_site_web_form_lead_counts(self):
		assert conversions.counts_as_lead(**LEAD)

	@pytest.mark.parametrize(
		"change",
		[
			{"public_site": None},
			{"public_site": ""},
			{"source": "Email"},
			{"source": None},
			{"web_form": ""},
			{"web_form": None},
			{"web_form": "waitlist-chronos"},
			{"email": "zephyrex-site-test+run1-contact@example.com"},
			{"email": " Someone@EXAMPLE.COM "},
		],
	)
	def test_anything_else_does_not(self, change):
		assert not conversions.counts_as_lead(**(LEAD | change))

	def test_a_lead_without_an_email_still_counts(self):
		assert conversions.counts_as_lead(**(LEAD | {"email": None}))


class TestPendingCookie:
	def test_lead_event_params_match_the_plugin(self):
		assert conversions.lead_event("contact-zephyrex-ca", "Contact") == {
			"e": "generate_lead",
			"p": {"form_id": "contact-zephyrex-ca", "form_name": "Contact"},
		}
		assert conversions.lead_event("f")["p"]["form_name"] == "f"

	def test_round_trip(self):
		event = conversions.lead_event("contact-zephyrex-ca", "Contact — été")
		value = conversions.append(None, event)
		assert conversions.decode(value) == [event]

	def test_value_is_unpadded_base64url_json(self):
		value = conversions.encode([conversions.lead_event("f", "?>?>")])
		assert "=" not in value and "+" not in value and "/" not in value
		raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
		assert json.loads(raw) == [{"e": "generate_lead", "p": {"form_id": "f", "form_name": "?>?>"}}]

	def test_keeps_the_newest_few(self):
		value = None
		for i in range(conversions.MAX_PENDING + 3):
			value = conversions.append(value, conversions.lead_event(f"f{i}"))
		forms = [e["p"]["form_id"] for e in conversions.decode(value)]
		assert forms == [f"f{i}" for i in range(3, conversions.MAX_PENDING + 3)]

	@pytest.mark.parametrize("value", [None, "", "!!!", "e30", conversions.encode({"e": "generate_lead"})])
	def test_malformed_values_decode_to_nothing(self, value):
		assert conversions.decode(value) == []

	def test_unknown_events_and_odd_params_are_dropped(self):
		value = conversions.encode(
			[
				{"e": "purchase", "p": {}},
				{"e": "generate_lead", "p": {"form_id": "f", "nested": {"x": 1}, "n": 2}},
				{"e": "click_email", "p": "x"},
				"junk",
			]
		)
		assert conversions.decode(value) == [
			{"e": "generate_lead", "p": {"form_id": "f", "n": 2}},
			{"e": "click_email", "p": {}},
		]
