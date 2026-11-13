from floatnote.words import suggest_fix


def test_single_word_replacement():
    assert suggest_fix("The whitetail admin is broken.", "The Wagtail admin is broken.") == ("whitetail", "Wagtail")


def test_phrase_replacement():
    assert suggest_fix("the white tail admin", "the Wagtail admin") == ("white tail", "Wagtail")


def test_case_change():
    assert suggest_fix("the api returns 500", "the API returns 500") == ("api", "API")


def test_additions_deletions_and_rewrites_are_ignored():
    assert suggest_fix("button broken", "button broken on mobile") is None
    assert suggest_fix("the button is broken on mobile", "the button is broken") is None
    assert suggest_fix("one two three four five", "six seven eight nine ten") is None
    assert suggest_fix("same text", "same text") is None


def test_known_fix_not_offered_again():
    assert suggest_fix("the whitetail admin", "the Wagtail admin", {"whitetail": "Wagtail"}) is None
