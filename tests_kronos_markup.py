import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

class IDs(HTMLParser):
    def __init__(self):super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        value=dict(attrs).get('id')
        if value:self.ids.append(value)

class KronosMarkup(unittest.TestCase):
    def test_unique_ids(self):
        parser=IDs();parser.feed((Path(__file__).parent/'templates/kronos.html').read_text())
        self.assertEqual([k for k,n in Counter(parser.ids).items() if n>1],[])
    def test_one_report_within_primary_content(self):
        html=(Path(__file__).parent/'templates/kronos.html').read_text()
        self.assertEqual(html.count('id="dailySummary"'),1)
        self.assertLess(html.index('class="primary"'),html.index('id="dailySummary"'))
        self.assertLess(html.index('id="dailySummary"'),html.index('<aside'))

if __name__=='__main__':unittest.main()
