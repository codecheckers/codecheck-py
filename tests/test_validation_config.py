"""
Tests for the helpers in validation_config.py shared by the modules
"""
import pytest

from validation_config import Person, people


@pytest.mark.parametrize('config,role,expected', [
    ({'codechecker': {'name': 'A'}}, 'codechecker', [('codechecker', 'Codechecker', {'name': 'A'})]),
    ({'codechecker': [{'name': 'A'}]}, 'codechecker', [('codechecker', 'Codechecker', {'name': 'A'})]),
    ({'codechecker': [{'name': 'A'}, 'bad']}, 'codechecker',
     [('codechecker[0]', 'Codechecker 1', {'name': 'A'}), ('codechecker[1]', 'Codechecker 2', 'bad')]),
    ({'paper': {'authors': [{'name': 'B'}]}}, 'author', [('paper.authors[0]', 'Author 1', {'name': 'B'})]),
    ({'paper': {'authors': {'name': 'B'}}}, 'author', []),  # the specification requires a list
    ({'paper': 'x'}, 'author', []), ({'codechecker': 'x'}, 'codechecker', []), (None, 'author', []),
])
def test_people(config, role, expected):
    result = people(config, role)
    assert result == expected and all(isinstance(p, Person) for p in result)


def test_people_fields():
    person = people({'codechecker': [{'name': 'A'}, {'name': 'B'}]}, 'codechecker')[1]
    assert (person.field, person.label, person.entry) == ('codechecker[1]', 'Codechecker 2', {'name': 'B'})


def test_people_unknown_role():
    with pytest.raises(KeyError):
        people({}, 'editor')
