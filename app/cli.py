import csv
import io
import json
from pathlib import Path
import typer
from app.guard import enable_offline, verify_model
from app.config import load
from app.store import Store
from app import actions

cli = typer.Typer(help='Local File Intel — offline document understanding and reversible organization.')
audit_cli = typer.Typer()
models_cli = typer.Typer()
eval_cli = typer.Typer()
cli.add_typer(audit_cli, name='audit')
cli.add_typer(models_cli, name='models')
cli.add_typer(eval_cli, name='eval')
CONFIG = None

@cli.callback()
def main(config: Path = typer.Option(None, '--config', help='Path to config.toml')):
    global CONFIG
    CONFIG = load(config)
    enable_offline()

def emit(value):
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))

@cli.command()
def scan():
    from app.discover import discover
    s = Store(CONFIG)
    try:
        emit({'changed_file_ids': discover(CONFIG, s)})
    finally:
        s.close()

@cli.command()
def index(rebuild: bool = typer.Option(False, '--rebuild', help='Regenerate derived content and vectors without changing sources'),
          retry_failed: bool = typer.Option(False, '--retry-failed', help='Retry unreadable files after fixing the cause')):
    from app.pipeline import index as run
    emit(run(CONFIG, rebuild=rebuild, retry_failed=retry_failed))

@cli.command()
def dedupe():
    from app.analyze import dedupe as run
    s = Store(CONFIG)
    try:
        emit({'pairs': run(s, CONFIG)})
    finally:
        s.close()

@cli.command()
def cluster():
    from app.analyze import cluster as run
    s = Store(CONFIG)
    try:
        emit(run(s, CONFIG))
    finally:
        s.close()

@cli.command()
def search(query: str, mode: str = 'hybrid', limit: int = 10, file_type: str = ''):
    from app.search import search as run
    if mode not in ('hybrid', 'keyword', 'semantic'):
        raise typer.BadParameter('mode must be hybrid, keyword or semantic')
    s = Store(CONFIG)
    try:
        emit(run(s, CONFIG, query, limit=limit, mode=mode, type_filter=file_type))
    finally:
        s.close()

@cli.command()
def propose(kind: str, src: Path, dst: Path = None):
    s = Store(CONFIG)
    try:
        emit({'action_id': actions.propose(s, CONFIG, kind, src, dst)})
    finally:
        s.close()

@cli.command()
def approve(action_id: int, actor: str = 'user'):
    s = Store(CONFIG)
    try:
        actions.approve(s, action_id, actor)
        emit({'approved': action_id})
    finally:
        s.close()

@cli.command()
def apply(action_id: int):
    s = Store(CONFIG)
    try:
        actions.apply(s, CONFIG, action_id)
        emit({'executed': action_id})
    finally:
        s.close()

@cli.command()
def undo(action_id: int):
    s = Store(CONFIG)
    try:
        actions.undo(s, CONFIG, action_id)
        emit({'undone': action_id})
    finally:
        s.close()

@cli.command()
def reject(action_id: int):
    s = Store(CONFIG)
    try:
        actions.reject(s, action_id)
        emit({'rejected': action_id})
    finally:
        s.close()

@cli.command()
def recover():
    s = Store(CONFIG)
    try:
        emit(actions.recover(s, CONFIG))
    finally:
        s.close()

@cli.command()
def export(format: str = 'json'):
    """Print an export to stdout. Redirect to a location outside source roots."""
    s = Store(CONFIG)
    try:
        rows = s.rows('''SELECT f.path,f.magika_label,d.title,d.extraction_status,d.text_sha256
            FROM files f LEFT JOIN documents d USING(file_id) WHERE f.status='present' ''')
        if format == 'json':
            emit(rows)
        elif format == 'csv':
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=['path', 'magika_label', 'title', 'extraction_status', 'text_sha256'])
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v) for k, v in row.items()})
            typer.echo(buf.getvalue())
        elif format == 'markdown':
            typer.echo('# File inventory\n\n' + '\n'.join('- `' + r['path'].replace('`', '') + '` — ' + str(r['extraction_status']) for r in rows))
        else:
            raise typer.BadParameter('format must be json, csv, or markdown')
    finally:
        s.close()

@cli.command()
def ask(question: str, llm: bool = typer.Option(True, '--llm/--no-llm', help='Write the answer with the local model')):
    """Answer a question from the indexed files, citing the passages used."""
    from app.ask import ask as run
    generator = None
    if llm:
        try:
            from app.local_model import LocalAnswerer
            generator = LocalAnswerer(CONFIG)
        except Exception as exc:
            typer.echo(f'Local model unavailable ({exc}); quoting the closest sentences.', err=True)
    s = Store(CONFIG)
    try:
        emit(run(s, CONFIG, question, generate=generator))
    finally:
        s.close()

@cli.command()
def similar(path: Path, limit: int = 8):
    """List the indexed files closest in meaning to one file."""
    from app.search import similar as run
    s = Store(CONFIG)
    try:
        row = s.one('SELECT d.document_id FROM documents d JOIN files f USING(file_id) WHERE f.path=?', (str(path.resolve()),))
        if not row:
            raise typer.BadParameter('That file is not in the index')
        emit(run(s, row['document_id'], limit))
    finally:
        s.close()

@cli.command()
def facts(path: Path = typer.Argument(None, help='Show one file; omit to refresh facts for the whole index')):
    """Key facts (amounts, dates, references, organisations, emails) found in indexed files."""
    from app.facts import refresh
    s = Store(CONFIG)
    try:
        if path is None:
            emit({'facts_added': refresh(s)})
        else:
            emit([r['tag'] for r in s.rows('''SELECT t.tag FROM tags t JOIN documents d USING(document_id) JOIN files f USING(file_id)
                WHERE f.path=? AND t.source='fact' ORDER BY t.tag''', (str(path.resolve()),))])
    finally:
        s.close()

@cli.command()
def report(format: str = 'html'):
    """Print the review report (html or csv) to stdout."""
    from app.report import gather, to_csv, to_html
    if format not in ('html', 'csv'):
        raise typer.BadParameter('format must be html or csv')
    s = Store(CONFIG)
    try:
        data = gather(s)
        typer.echo(to_html(data) if format == 'html' else to_csv(data))
    finally:
        s.close()

@audit_cli.command('verify')
def audit_verify():
    s = Store(CONFIG)
    try:
        ok = s.verify_audit()
        emit({'valid': ok})
        if not ok:
            raise typer.Exit(1)
    finally:
        s.close()

@models_cli.command('verify')
def models_verify():
    report = {}
    for name in ('minilm', 'qwen', 'docling', 'ocr'):
        try:
            path, entry = verify_model(CONFIG.models, name)
            report[name] = {'verified': True, 'files': len(entry['files']), 'path': str(path)}
        except Exception as exc:
            report[name] = {'verified': False, 'error': str(exc)}
    emit(report)
    if not all(v['verified'] for v in report.values()):
        raise typer.Exit(1)

@eval_cli.command('run')
def eval_run():
    from eval.run import run
    emit(run(CONFIG))

if __name__ == '__main__':
    cli()
