from ff.values.normalize import normalize_name


def test_normalize_name_lowercasing():
    assert normalize_name("JaHmyr GiBbs") == "jahmyr gibbs"
    assert normalize_name("PATRICK MAHOMES") == "patrick mahomes"


def test_normalize_name_punctuation():
    # apostrophes
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("A.J. Brown") == "aj brown"
    assert normalize_name("D'Andre Swift") == "dandre swift"
    assert normalize_name("O'Dell Beckham") == "odell beckham"
    # backticks
    assert normalize_name("De`Von Achane") == "devon achane"
    # periods
    assert normalize_name("T.J. Hockenson") == "tj hockenson"


def test_normalize_name_non_alphanumeric():
    assert normalize_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert normalize_name("Juju Smith-Schuster") == "juju smith schuster"
    assert normalize_name("Marquez Valdes-Scantling") == "marquez valdes scantling"
    assert normalize_name("Kenneth Walker III") == "kenneth walker"


def test_normalize_name_generational_suffixes():
    assert normalize_name("Odell Beckham Jr.") == "odell beckham"
    assert normalize_name("Travis Etienne Jr.") == "travis etienne"
    assert normalize_name("Michael Pittman Jr") == "michael pittman"
    assert normalize_name("Patrick Mahomes II") == "patrick mahomes"
    assert normalize_name("Calvin Austin III") == "calvin austin"
    assert normalize_name("Eno Benjamin VII") == "eno benjamin vii"  # Not in suffix list


def test_normalize_name_valid_name_components_retained():
    # 'sr', 'jr', 'ii', 'iii', 'iv', 'v' as substrings shouldn't be removed, only as full words.
    assert normalize_name("Irv Smith Jr.") == "irv smith"
    assert normalize_name("Irv Smith") == "irv smith"
    assert normalize_name("Ivan Pace Jr.") == "ivan pace"
    assert normalize_name("Von Miller") == "von miller"
    assert normalize_name("Jr. Smith") == "smith"  # "jr" as a token is stripped
    assert normalize_name("Sirius Black") == "sirius black"


def test_normalize_name_multiple_spaces():
    assert normalize_name("  Derrick   Henry  ") == "derrick henry"
    assert normalize_name("Christian  McCaffrey") == "christian mccaffrey"
    assert normalize_name("Chris    Olave") == "chris olave"


def test_normalize_name_empty_or_whitespace():
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""
    assert normalize_name(" . ") == ""
