"""Render the editor's TikZ output as a tightly cropped picture."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from graph_builder_core.io.tikz import graph_to_tikz


PICTURE_SUFFIXES = ('.png', '.svg', '.pdf')


class PictureExportError(RuntimeError):
    """A missing renderer or invalid TikZ prevented picture export."""


def _contains_unescaped_hash(label):
    preceding_slashes = 0
    for character in str(label):
        if character == '#' and preceding_slashes % 2 == 0:
            return True
        preceding_slashes = preceding_slashes + 1 if character == '\\' else 0
    return False


def _latex_hint(graph, error):
    if not any(message in str(error) for message in
               ('Illegal parameter number', "macro parameter character #")):
        return ''
    candidates = []
    for node, attributes in graph.nodes(data=True):
        if _contains_unescaped_hash(attributes.get('label', node)):
            candidates.append(f'vertex {node!r}')
    for source, target, attributes in graph.edges(data=True):
        if _contains_unescaped_hash(attributes.get('label', '')):
            candidates.append(f'edge {source!r}–{target!r}')
    if candidates:
        return ('\nAn unescaped # appears in the label of '
                + ', '.join(candidates[:3]) + '. Use \\# for a literal #.')
    return ''


def _tool(name):
    found = shutil.which(name)
    if found:
        return found
    # GUI apps launched from Finder often lack paths used by Terminal.
    if sys.platform == 'darwin':
        for folder in ('/Library/TeX/texbin', '/opt/homebrew/bin', '/usr/local/bin',
                       '/Applications/Ipe.app/Contents/MacOS',
                       '/Applications/Ipe.app/Contents/Resources/local/bin'):
            candidate = Path(folder) / name
            if candidate.is_file():
                return str(candidate)
    return None


def _run(command, directory, stage):
    # Ipe launches pdflatex itself. Finding Ipe by absolute path does not
    # give its children the TeX search path missing from Finder launches.
    environment = os.environ.copy()
    latex = _tool('pdflatex')
    if latex:
        environment['PATH'] = os.pathsep.join(
            (str(Path(latex).parent), environment.get('PATH', os.defpath)))
    if Path(command[0]).stem == 'ipetoipe':
        # Keep conversion files out of Ipe's shared user cache, including
        # when the editor and Ipe are running at the same time.
        environment['IPELATEXDIR'] = str(Path(directory).resolve())
        if latex:
            environment['IPELATEXPATH'] = str(Path(latex).parent)
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True,
                                text=True, errors='replace', timeout=60, check=False,
                                env=environment)
    except subprocess.TimeoutExpired as error:
        raise PictureExportError(f'{stage} timed out after 60 seconds.') from error
    except OSError as error:
        raise PictureExportError(f'Could not start {stage}: {error}') from error
    if result.returncode:
        output = result.stdout + '\n' + result.stderr
        latex_error = next((line.strip() for line in output.splitlines()
                            if line.lstrip().startswith('!')), None)
        detail = latex_error or '\n'.join(output.splitlines()[-8:]).strip()
        raise PictureExportError(f'{stage} failed.\n{detail}')


def render_picture_pdf(graph, file_path):
    """Compile the graph's TikZ drawing to a cropped PDF for preview or export."""
    destination = Path(file_path)
    pdflatex = _tool('pdflatex')
    if not pdflatex:
        raise PictureExportError(
            'Rendering this picture requires pdflatex, TikZ and the '
            'standalone package from a LaTeX installation. You can still use '
            'Export to TikZ without installing LaTeX.')
    with tempfile.TemporaryDirectory(prefix='graph-builder-picture-') as temporary:
        work = Path(temporary)
        source = work / 'picture.tex'
        source.write_text(
            '\\documentclass[tikz,border=3pt]{standalone}\n'
            '\\begin{document}\n'
            + graph_to_tikz(graph)
            + '\\end{document}\n', encoding='utf-8')
        try:
            _run([pdflatex, '-no-shell-escape', '-interaction=nonstopmode',
                  '-halt-on-error', 'picture.tex'], work, 'LaTeX')
        except PictureExportError as error:
            raise PictureExportError(str(error) + _latex_hint(graph, error)) from error
        pdf = work / 'picture.pdf'
        if not pdf.is_file():
            raise PictureExportError('LaTeX did not produce a PDF picture.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, destination)
    return destination


def convert_picture_pdf(pdf_path, file_path, *, dpi=300, ipe_compatible=False):
    """Save an already rendered PDF as PDF, PNG, or SVG without recompiling."""
    source = Path(pdf_path)
    destination = Path(file_path)
    suffix = destination.suffix.lower()
    if suffix not in PICTURE_SUFFIXES:
        raise ValueError(f'Choose a picture format: {", ".join(PICTURE_SUFFIXES)}')
    if ipe_compatible:
        if suffix != '.pdf':
            raise ValueError('Ipe-compatible export requires a .pdf filename.')
        return _ipe_pdf(source, destination)
    if not 72 <= dpi <= 1200:
        raise ValueError('PNG resolution must be between 72 and 1200 dpi.')
    pdftocairo = _tool('pdftocairo') if suffix != '.pdf' else None
    dvisvgm = _tool('dvisvgm') if suffix == '.svg' else None
    if suffix == '.png' and not pdftocairo:
        raise PictureExportError('PNG export also requires the pdftocairo tool '
                                 'from Poppler. PDF export only needs LaTeX.')
    if suffix == '.svg' and not (pdftocairo or dvisvgm):
        raise PictureExportError('SVG export also requires pdftocairo (Poppler) '
                                 'or dvisvgm with PDF support.')
    if suffix == '.pdf':
        if source != destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return destination
    with tempfile.TemporaryDirectory(prefix='graph-builder-picture-convert-') as temporary:
        work = Path(temporary)
        rendered = work / ('picture' + suffix)
        if suffix == '.png':
            _run([pdftocairo, '-f', '1', '-singlefile', '-png', '-transp',
                  '-r', str(dpi), str(source), str(work / 'picture')],
                 work, 'PNG conversion')
        elif pdftocairo:
            _run([pdftocairo, '-svg', '-f', '1', '-l', '1',
                  str(source), str(rendered)], work, 'SVG conversion')
        else:
            _run([dvisvgm, '--pdf', '--page=1', '--no-fonts',
                  f'--output={rendered}', str(source)], work, 'SVG conversion')
        if not rendered.is_file():
            raise PictureExportError('The picture converter did not produce a file.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rendered, destination)
    return destination


def _ipe_pdf(source, destination):
    """Convert the rendered drawing into a PDF with editable Ipe objects."""
    pdftoipe, ipetoipe = _tool('pdftoipe'), _tool('ipetoipe')
    missing = [name for name, tool in (('pdftoipe', pdftoipe), ('ipetoipe', ipetoipe)) if not tool]
    if missing:
        raise PictureExportError(
            'Ipe-compatible PDF export needs ' + ', '.join(missing) + '. '
            'Install Ipe (ipetoipe) and the separate ipe-tools package (pdftoipe), '
            'and make their tools available on PATH. Ordinary PDF export remains available.')
    with tempfile.TemporaryDirectory(prefix='graph-builder-ipe-') as temporary:
        work = Path(temporary)
        xml = work / 'drawing.ipe'
        rendered = work / 'drawing.pdf'
        _run([pdftoipe, str(source.resolve()), str(xml)], work, 'PDF to Ipe conversion')
        _run([ipetoipe, '-pdf', str(xml), str(rendered)], work, 'Ipe PDF conversion')
        if not rendered.is_file() or not rendered.read_bytes().startswith(b'%PDF'):
            raise PictureExportError('Ipe did not produce a PDF document.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rendered, destination)
    return destination


def export_picture(graph, file_path, *, dpi=300, ipe_compatible=False):
    """Compile the graph's TikZ output and save it as PDF, PNG, or SVG."""
    with tempfile.TemporaryDirectory(prefix='graph-builder-picture-export-') as temporary:
        pdf = render_picture_pdf(graph, Path(temporary) / 'picture.pdf')
        return convert_picture_pdf(pdf, file_path, dpi=dpi, ipe_compatible=ipe_compatible)
