"""Exercise the real publication shell against local Git repositories only."""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW=Path(__file__).parent/'.github/workflows/kronos-inference.yml'

def git(directory,*args):
    return subprocess.check_output(['git',*args],cwd=directory,stderr=subprocess.DEVNULL,text=True)

class Publication(unittest.TestCase):
    def test_failure_status_preserves_forecasts_without_optional_report_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);seed=root/'seed';seed.mkdir()
            git(seed,'init','-b','kronos-forecasts');git(seed,'config','user.name','test');git(seed,'config','user.email','test@example.test')
            (seed/'forecasts').mkdir();(seed/'forecasts/original.json').write_text('{"fixture":true}')
            (seed/'index.json').write_text('{"forecasts":["original"]}')
            (seed/'README.txt').write_text('Existing publication metadata')
            (seed/'status.json').write_text('{"status":"ready"}')
            git(seed,'add','.');git(seed,'commit','-m','Fixture')
            remote=root/'remote.git';git(root,'clone','--bare',str(seed),str(remote))
            published=root/'published';shutil.copytree(seed,published,ignore=shutil.ignore_patterns('.git'))
            (published/'status.json').write_text('{"status":"failed"}')
            script=textwrap.dedent(WORKFLOW.read_text().split('        run: |')[-1])
            script=script.replace('test -f /tmp/published/status.json','test -f status.json').replace('cd /tmp/published','').replace('gh auth setup-git',':').replace('"https://github.com/$GITHUB_REPOSITORY.git"','"$TEST_REMOTE"')
            subprocess.run(['bash','-e','-c',script],cwd=published,env={**os.environ,'TEST_REMOTE':str(remote)},check=True,capture_output=True)
            for path in ['index.json','forecasts/original.json','README.txt']:
                self.assertEqual(git(root,'--git-dir='+str(remote),'show','kronos-forecasts:'+path).strip(),(seed/path).read_text())
            self.assertEqual(json.loads(git(root,'--git-dir='+str(remote),'show','kronos-forecasts:status.json'))['status'],'failed')
    def test_startup_retry_is_bounded_and_recovers(self):
        workflow=WORKFLOW.read_text()
        block=workflow.split('      - name: Run genuine inference with feed freshness guard',1)[1].split('      - name: Publish results',1)[0]
        script=textwrap.dedent(block.split('        run: |',1)[1])
        prefix='n=0; python(){ n=$((n+1)); [ "$n" -ge 2 ]; }; sleep(){ :; };\n'
        subprocess.run(['bash','-e','-c',prefix+script],check=True,capture_output=True)
        self.assertIn('for attempt in 1 2 3 4',script)

if __name__=='__main__':unittest.main()
