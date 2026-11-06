import unittest,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from identities import title_for,identity,migrate
class IdentityTests(unittest.TestCase):
 def test_titles(self):
  self.assertEqual(title_for('正文','自定','文稿.txt'),('自定','custom'))
  self.assertEqual(title_for('正文',filename='朗读稿.txt'),('朗读稿','filename'))
  self.assertEqual(title_for('  第一行  文本。第二句'),('第一行 文本','text'))
  self.assertEqual(title_for('长'*25)[0],'长'*24+'…')
  self.assertEqual(title_for('？！……')[1],'fallback')
 def test_migration_idempotent(self):
  c=sqlite3.connect(':memory:');c.execute('CREATE TABLE tasks(id TEXT,title TEXT,voice TEXT,text TEXT)')
  c.executemany('INSERT INTO tasks VALUES(?,?,?,?)',[('a','保留标题','si','正文'),('b','导入','si',''),('c','旧作品','unknown','正文')])
  migrate(c);migrate(c)
  self.assertEqual(c.execute('SELECT text_lang,postprocess,raw_available FROM tasks WHERE id="a"').fetchone(),('zh',0,0))
  self.assertEqual(c.execute('SELECT title,source_type FROM tasks WHERE id="a"').fetchone(),('保留标题','synthesis'))
  self.assertEqual(c.execute('SELECT source_type FROM tasks WHERE id="b"').fetchone()[0],'import')
  self.assertIsNone(identity('unknown')['avatar'])
  self.assertEqual(identity('si')['name'],'祀');self.assertTrue(identity('si')['avatar'].startswith('/media/voices/'))
if __name__=='__main__':unittest.main()
