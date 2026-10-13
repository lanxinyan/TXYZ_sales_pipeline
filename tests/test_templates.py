from sales_pipeline.templates import followup_variants, load, quote_block, render


def test_bundled_follow_ups_escalate_through_four_stages():
    T = load()
    first = {n: followup_variants(T, n, quote_sent=True)[0] for n in range(1, 5)}
    assert "received our previous email" in first[1].body
    assert "had a chance to review" in first[2].body
    assert "decision has been made on this quote" in first[3].body
    assert "courtesy reply" in first[4].body and "stop further follow-ups" in first[4].body
    assert [t.key for t in followup_variants(T, 2, True)] == ["followup_2", "followup_2b"]


def test_stage_three_depends_on_whether_a_quote_was_sent():
    T = load()
    assert followup_variants(T, 3, quote_sent=True)[0].key == "followup_3_quote"
    assert followup_variants(T, 3, quote_sent=False)[0].key == "followup_3_service"


def test_render_fills_details_and_blanks_unknowns():
    T = load()
    text = render(T["followup_1"], greeting="Hi Robin,", sender_name="Tony", sender_phone="1-631-559-9269",
                  signature="Best regards,\n\nTony")
    assert text.startswith("Hi Robin,\n\nThis is Tony.")
    assert "1-631-559-9269" in text and text.rstrip().endswith("Tony")
    assert "{" not in render(T["first_reply"])                 # missing values never leak braces


def test_custom_template_file(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("# my wording\n=== followup_1 | Short ===\n{greeting}\n\nAny news?\n\n{signature}\n", encoding="utf-8")
    T = load(str(f))
    assert T["followup_1"].label == "Short" and "revisit_quote" in T     # built-ins it lacks are kept
    assert render(T["followup_1"], greeting="Hello,", signature="Tony") == "Hello,\n\nAny news?\n\nTony\n"


def test_previous_email_is_quoted_gmail_style():
    q = quote_block({"sender": "Tony <t@x.com>", "date_label": "Thu, Oct 8", "body": "Line 1\n\nLine 2"})
    assert q == "\n\nOn Thu, Oct 8, Tony <t@x.com> wrote:\n> Line 1\n>\n> Line 2\n"
    assert quote_block(None) == ""


def test_subjects_read_naturally_in_a_sentence():
    from sales_pipeline.tasks import topic_phrase

    assert topic_phrase("Exosome isolation quote") == "exosome isolation"
    assert topic_phrase("Request for Quotation - HDX-MS epitope mapping") == "HDX-MS epitope mapping"
    assert topic_phrase("Cryo-EM for a membrane protein") == "Cryo-EM for a membrane protein"
