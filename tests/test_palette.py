from clicker import palette


def titles(q, items):
    return [i["title"] for i in palette.rank(q, items)]


ITEMS = [{"title": "New script"}, {"title": "Start recording"}, {"title": "Save script as"},
         {"title": "Go to Screen Triggers"}, {"title": "Settings", "keywords": "preferences options hotkeys"},
         {"title": "New step: Type Text"}, {"title": "Stop everything"}]


def test_word_starts_beat_the_middle_of_words():
    assert titles("rec", ITEMS)[0] == "Start recording"
    assert titles("sett", ITEMS)[0] == "Settings"


def test_initials_and_letters_in_order():
    assert titles("nsc", ITEMS)[0] == "New script"
    assert titles("gst", ITEMS)[0] == "Go to Screen Triggers"


def test_every_word_must_match_in_any_order():
    assert titles("script save", ITEMS) == ["Save script as"]
    assert titles("zzz", ITEMS) == []


def test_keywords_find_things_by_other_names():
    assert titles("preferences", ITEMS) == ["Settings"]


def test_empty_query_keeps_the_given_order_and_boost_wins_ties():
    assert titles("", ITEMS) == [i["title"] for i in ITEMS]
    items = [{"title": "Open A"}, {"title": "Open B", "boost": 5}]
    assert titles("open", items) == ["Open B", "Open A"]
