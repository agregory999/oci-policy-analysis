import logging
import re
import traceback


def clean_markdown(markdown_text) -> str:
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


def exception_to_html(exc_type, exc_value, exc_traceback):
    """
    Converts an exception's details into a formatted HTML string.

    Args:
        exc_type: The type of the exception.
        exc_value: The exception instance.
        exc_traceback: The traceback object.

    Returns:
        A string containing the formatted HTML representation of the exception.
    """
    html_template = """
    <html>

    <body style="font-family: sans-serif; margin: 20px; background-color: #f4f4f4;>
        <div style="background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h1 style="color: #d9534f;">An Exception Occurred!</h1>
            <h2 style="color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 20px;">Error Details</h2>
            <p style="color: #a94442; font-weight: bold;"><strong>Type:</strong> {exc_type_name}</p>
            <p style="color: #a94442; font-weight: bold;"><strong>Message:</strong> {exc_message}</p>
            <h2 style="color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 20px;">Traceback</h2>
            <pre style="background-color: #eee; padding: 15px; border-radius: 4px; overflow-x: auto;">{traceback_formatted}</pre>
        </div>
    </body>
    </html>
    """

    # Format the traceback as a string
    formatted_traceback = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    # Prepare the data for the HTML template
    exc_type_name = exc_type.__name__
    exc_message = str(exc_value)

    # Fill the HTML template with exception details
    return html_template.format(
        exc_type_name=exc_type_name, exc_message=exc_message, traceback_formatted=formatted_traceback
    )


def format_dgrule(text, indent_level=0) -> str:  # noqa: C901
    """
    Recursively formats the input language string with 2-space indentation.

    Args:
        text (str): The input language string to format
        indent_level (int): Current indentation level (default: 0)

    Returns:
        str: Formatted string with newlines and 2-space indentation
    """
    result = []
    current = ''
    i = 0
    while i < len(text):
        char = text[i]

        if char == '{':
            result.append('  ' * indent_level + current.strip() + ' {')
            brace_count = 1
            start = i + 1
            while i < len(text) and brace_count > 0:
                i += 1
                if i < len(text):
                    if text[i] == '{':
                        brace_count += 1
                    elif text[i] == '}':
                        brace_count -= 1
            result.append(format_dgrule(text[start:i], indent_level + 1))
            current = ''
            continue
        elif char == '}':
            if current.strip():
                result.append('  ' * indent_level + current.strip())
            result.append('  ' * indent_level + '}')
            current = ''
        elif char == ',':
            if current.strip():
                result.append('  ' * indent_level + current.strip())
            current = ''
        else:
            current += char
        i += 1

    if current.strip():
        result.append('  ' * indent_level + current.strip())

    return '\n'.join(line for line in result if line.strip())
