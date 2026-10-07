"""Plain URLs in Markdown become links in the PDF, as they are in Jupyter (markdown_links.py)."""
import nbformat
import pytest

from markdown_links import link_notebook, link_urls


@pytest.mark.parametrize('text,expected', [
    ('See https://example.org/a_b?x=1.', 'See <https://example.org/a_b?x=1>.'),
    ('http://example.org, and more', '<http://example.org>, and more'),
    ('(see https://example.org/x)', '(see <https://example.org/x>)'),
    ('https://en.wikipedia.org/wiki/Foo_(bar)', '<https://en.wikipedia.org/wiki/Foo_(bar)>'),
    ('www.example.net!', '[www.example.net](http://www.example.net)!'),
    ('| a | https://example.org |', '| a | <https://example.org> |'),
    ('line one\nhttps://example.org\n', 'line one\n<https://example.org>\n'),
])
def test_plain_urls_become_links(text, expected):
    assert link_urls(text) == expected


@pytest.mark.parametrize('text', [
    '`https://example.org`',
    '``a ` https://example.org``',
    '[https://example.org](https://example.org)',
    '[text](https://example.org/a_(b)) and ![alt](<outputs/a b.png>)',
    '[text][ref]\n\n[ref]: https://example.org',
    '<https://example.org> and <a href="https://example.org">x</a>',
    '```\nhttps://example.org\n```\n',
    '~~~~\n~~~\nhttps://example.org\n~~~~\n',
    'https:// and www.x and mail@https://example.org',
    '    curl https://example.org/api\n',
    'Text\n\n    code https://example.org\n\n    more https://example.org\n',
    'https://example.org/x\\_y',
])
def test_code_links_and_html_are_left_alone(text):
    assert link_urls(text) == text


def test_text_after_a_code_block_is_linked():
    assert link_urls('```python\nx = "https://a.org"\n```\nhttps://b.org') == \
        '```python\nx = "https://a.org"\n```\n<https://b.org>'


@pytest.mark.parametrize('text,expected', [
    ('[a]: https://a.org\n\nSee https://b.org now', '[a]: https://a.org\n\nSee <https://b.org> now'),
    ('x < 3 or https://b.org > 2', 'x < 3 or <https://b.org> > 2'),
    ('para\n    continued https://b.org', 'para\n    continued <https://b.org>'),  # no code block: no blank line
    ('    code https://a.org\n\nafter https://b.org', '    code https://a.org\n\nafter <https://b.org>'),
])
def test_review_cases(text, expected):
    assert link_urls(text) == expected


def test_unclosed_backtick_does_not_hide_later_paragraphs():
    assert link_urls('a ` b\n\nhttps://example.org') == 'a ` b\n\n<https://example.org>'


def test_notebook_markdown_cells_and_outputs(tmp_path):
    path = tmp_path / 'nb.ipynb'
    code = nbformat.v4.new_code_cell('print("https://example.org/code")', outputs=[
        nbformat.v4.new_output('stream', name='stdout', text='https://example.org/stream'),
        nbformat.v4.new_output('display_data', data={'text/markdown': 'Summary https://example.org/b',
                                                     'text/plain': 'https://example.org/p'}),
    ])
    nbformat.write(nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell('Notes: https://example.org/a\nend'), code]), path)
    link_notebook(path)
    cells = nbformat.read(path, as_version=4).cells
    assert cells[0].source == 'Notes: <https://example.org/a>\nend'
    assert cells[1].source == 'print("https://example.org/code")'
    outputs = cells[1].outputs
    assert outputs[0].text == 'https://example.org/stream'
    assert outputs[1].data == {'text/markdown': 'Summary <https://example.org/b>', 'text/plain': 'https://example.org/p'}
