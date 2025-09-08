import logging
import re
import tkinter as tk


def clean_markdown(markdown_text):
    """Remove empty list items and excessive newlines from markdown text."""
    logging.debug('Cleaning markdown text: %s', str(markdown_text)[:100])
    if not isinstance(markdown_text, str):
        logging.warning('clean_markdown received non-string input: %s', type(markdown_text))
        return markdown_text

    lines = markdown_text.split('\n')
    cleaned_lines = []
    in_code_block = False

    for line in lines:
        line = line.rstrip()
        if line.strip() == '```':
            in_code_block = not in_code_block
            cleaned_lines.append(line)
            continue
        if not in_code_block and (
            line.strip() in ['-', '*', '1.', '- ', '* ', '1. '] or re.match(r'^\d+\.\s*$', line.strip())
        ):
            logging.debug('Skipping empty list item: %s', line)
            continue
        cleaned_lines.append(line)

    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
    logging.debug('Cleaned markdown: %s', result[:100])
    return result


def insert_markdown(text_widget, markdown_text):  # noqa: C901
    """Insert markdown text into the Text widget with formatting."""
    logging.debug('Starting insert_markdown with input type: %s', type(markdown_text))

    text_widget.delete(1.0, tk.END)
    logging.debug('Text widget cleared')

    if markdown_text is None:
        logging.error('Markdown text is None')
        text_widget.insert(tk.END, 'Error: Markdown text is None\n')
        return
    if not isinstance(markdown_text, str):
        logging.error('Invalid markdown text type: %s, content: %s', type(markdown_text), str(markdown_text)[:100])
        text_widget.insert(tk.END, f'Error: Invalid markdown text format: {type(markdown_text)}\n')
        return

    text_widget.tag_configure('bold', font=('Helvetica', 10, 'bold'), foreground='black')
    text_widget.tag_configure('italic', font=('Helvetica', 10, 'italic'), foreground='black')
    text_widget.tag_configure('code', font=('Courier New', 10), foreground='blue', background='#d0d0d0')
    text_widget.tag_configure('header1', font=('Helvetica', 16, 'bold'), foreground='black')
    text_widget.tag_configure('header2', font=('Helvetica', 14, 'bold'), foreground='black')
    text_widget.tag_configure('header3', font=('Helvetica', 12, 'bold'), foreground='black')
    text_widget.tag_configure('list', lmargin2=40)
    text_widget.tag_raise('code')
    text_widget.tag_raise('bold')
    logging.debug('Text widget tags configured')

    if not markdown_text.strip():
        logging.warning('Markdown text is empty or whitespace-only')
        text_widget.insert(tk.END, 'No content to display\n')
        return

    lines = markdown_text.split('\n')
    logging.debug('Processing %d lines of markdown text', len(lines))

    in_code_block = False
    for line_num, line in enumerate(lines, 1):
        line = line.rstrip()
        logging.debug('Processing line %d: %s', line_num, line[:100])

        if line.strip() == '```':
            in_code_block = not in_code_block
            text_widget.insert(tk.END, line + '\n', 'code' if in_code_block else '')
            logging.debug('Toggled code block: in_code_block=%s', in_code_block)
            continue

        if in_code_block:
            text_widget.insert(tk.END, line + '\n', 'code')
            logging.debug('Inserted code block line')
            continue

        if line.startswith('# '):
            text_widget.insert(tk.END, line[2:].strip() + '\n', 'header1')
            logging.debug('Inserted header1: %s', line[2:].strip())
        elif line.startswith('## '):
            text_widget.insert(tk.END, line[3:].strip() + '\n', 'header2')
            logging.debug('Inserted header2: %s', line[3:].strip())
        elif line.startswith('### '):
            text_widget.insert(tk.END, line[4:].strip() + '\n', 'header3')
            logging.debug('Inserted header3: %s', line[4:].strip())
        elif line.startswith('- ') or line.startswith('* '):
            text_widget.insert(tk.END, line.strip() + '\n', 'list')
            logging.debug('Inserted list item: %s', line.strip())
        else:
            start = 0
            try:
                for match in re.finditer(
                    r'(?<!\\)\*\*\s*([^\s*][^*]*?[^\s*])\s*(?<!\\)\*\*|'
                    r'(?<!\\)\*\s*([^\s*][^*]*?[^\s*])\s*(?<!\\)\*|'
                    r'(?<!\\)`\s*([^\s`][^`]*?[^\s`])\s*(?<!\\)`',
                    line,
                ):
                    if start < match.start():
                        text_widget.insert(tk.END, line[start : match.start()])
                        logging.debug('Inserted plain text: %s', line[start : match.start()])

                    if match.group(1):
                        text_widget.insert(tk.END, match.group(1).strip(), 'bold')
                        logging.debug('Inserted bold text: %s', match.group(1).strip())
                    elif match.group(2):
                        text_widget.insert(tk.END, match.group(2).strip(), 'italic')
                        logging.debug('Inserted italic text: %s', match.group(2).strip())
                    elif match.group(3):
                        text_widget.insert(tk.END, match.group(3).strip(), 'code')
                        logging.debug('Inserted inline code: %s', match.group(3).strip())

                    start = match.end()

                if start < len(line):
                    text_widget.insert(tk.END, line[start:] + '\n')
                    logging.debug('Inserted remaining text: %s', line[start:])
                else:
                    text_widget.insert(tk.END, '\n')
                    logging.debug('Inserted newline after inline formatting')
            except re.error as e:
                logging.error('Regex error in line %d: %s', line_num, e)
                text_widget.insert(tk.END, line + '\n')
                continue
