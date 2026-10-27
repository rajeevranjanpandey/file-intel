"""Small, human-readable fixtures for cross-format content grouping."""
from pathlib import Path

TITLE = 'Orion garden project'
BODY = ('The Orion garden project will plant twelve native trees beside the library. '
        'Volunteers will water the trees every Monday. The project budget is 4200 AED. '
        'The first planting day is 18 October 2026.')


def build(root):
    # ReportLab is used only by this fixture generator, not by the application.
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    root = Path(root)
    for folder in ('Markdown', 'Text', 'PDF'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / 'Markdown/orion-plan.md').write_text(f'# {TITLE}\n\n{BODY}\n')
    plain = f'{TITLE}\n\n{BODY}\n'
    (root / 'Text/orion-plan.txt').write_text(plain)
    (root / 'Text/orion-copy.txt').write_text(plain)
    (root / 'Markdown/orion-revised.md').write_text(f'# {TITLE}\n\n{BODY.replace("4200", "6500")}\n')
    (root / 'Text/pasta-recipe.txt').write_text(
        'Tomato pasta recipe\n\nBoil pasta in salted water. Fry garlic in olive oil. '
        'Add tomatoes and basil, simmer for fifteen minutes, and serve with cheese.\n')
    styles = getSampleStyleSheet()
    pdf = root / 'PDF/orion-plan.pdf'
    SimpleDocTemplate(str(pdf), title=TITLE, author='File Intel sample',
                      leftMargin=60, rightMargin=60, topMargin=60).build([
        Paragraph(TITLE, styles['Title']), Spacer(1, 20), Paragraph(BODY, styles['BodyText'])])
    return root


if __name__ == '__main__':
    import sys
    print(build(sys.argv[1]))
