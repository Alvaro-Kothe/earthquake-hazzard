from src.dags.get_country_info import reverse_geocode


def test_reverse_geocode():
    points = [
        (2.2943506, 48.8588443),
        (-134.23096, 56.03735),
        (-125.33203, -76.14404),
        (-135.87891, -43.63738),
    ]
    expected_locations = [
        ["France", "Europe"],
        ["United States of America", "North America"],
        ["Antarctica", "Antarctica"],
        [None, None],
    ]
    assert reverse_geocode(points, 300000) == expected_locations
