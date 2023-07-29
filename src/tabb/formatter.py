import re
import shutil
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from textwrap import TextWrapper

_ansi_re = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Removes ANSI color codes from a string."""
    return _ansi_re.sub("", text)


def term_len(text: str) -> int:
    """Returns the length of a string as it would be displayed on the
    terminal.  This is done by stripping ANSI color codes first.  If
    you don't want that, use ``len(strip_ansi(text))`` instead.
    """
    return len(strip_ansi(text))


def measure_table(rows: Iterable[tuple[str, str]]) -> tuple[int, ...]:
    widths: dict[int, int] = {}

    for row in rows:
        for idx, col in enumerate(row):
            widths[idx] = max(widths.get(idx, 0), term_len(col))

    return tuple(y for x, y in sorted(widths.items()))


def iter_rows(
    rows: Iterable[tuple[str, str]], col_count: int
) -> Iterator[tuple[str, ...]]:
    for row in rows:
        yield row + ("",) * (col_count - len(row))


@contextmanager
def extra_indent(wrapper: TextWrapper, indent: str) -> Iterator[None]:
    old_initial_indent = wrapper.initial_indent
    old_subsequent_indent = wrapper.subsequent_indent
    wrapper.initial_indent += indent
    wrapper.subsequent_indent += indent

    try:
        yield
    finally:
        wrapper.initial_indent = old_initial_indent
        wrapper.subsequent_indent = old_subsequent_indent


def indent_only(wrapper: TextWrapper, text: str) -> str:
    rv = []

    for idx, line in enumerate(text.splitlines()):
        indent = wrapper.initial_indent

        if idx > 0:
            indent = wrapper.subsequent_indent

        rv.append(f"{indent}{line}")

    return "\n".join(rv)


def wrap_text(
    text: str,
    width: int = 78,
    initial_indent: str = "",
    subsequent_indent: str = "",
    preserve_paragraphs: bool = False,
) -> str:
    """A helper function that intelligently wraps text.  By default, it
    assumes that it operates on a single paragraph of text but if the
    `preserve_paragraphs` parameter is provided it will intelligently
    handle paragraphs (defined by two empty lines).

    If paragraphs are handled, a paragraph can be prefixed with an empty
    line containing the ``\\b`` character (``\\x08``) to indicate that
    no rewrapping should happen in that block.

    :param text: the text that should be rewrapped.
    :param width: the maximum width for the text.
    :param initial_indent: the initial indent that should be placed on the
                           first line as a string.
    :param subsequent_indent: the indent string that should be placed on
                              each consecutive line.
    :param preserve_paragraphs: if this flag is set then the wrapping will
                                intelligently handle paragraphs.
    """
    text = text.expandtabs()
    wrapper = TextWrapper(
        width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        replace_whitespace=False,
    )
    if not preserve_paragraphs:
        return wrapper.fill(text)

    p: list[tuple[int, bool, str]] = []
    buf: list[str] = []
    indent = None

    def _flush_par() -> None:
        if not buf:
            return
        if buf[0].strip() == "\b":
            p.append((indent or 0, True, "\n".join(buf[1:])))
        else:
            p.append((indent or 0, False, " ".join(buf)))
        del buf[:]

    for line in text.splitlines():
        if not line:
            _flush_par()
            indent = None
        else:
            if indent is None:
                orig_len = term_len(line)
                line = line.lstrip()  # noqa: PLW2901
                indent = orig_len - term_len(line)
            buf.append(line)

    _flush_par()

    rv = []
    for indent, raw, text in p:
        with extra_indent(wrapper, " " * indent):
            if raw:
                rv.append(indent_only(wrapper, text))
            else:
                rv.append(wrapper.fill(text))

    return "\n\n".join(rv)


def make_default_short_help(help: str, max_length: int = 45) -> str:
    """Returns a condensed version of help string."""
    # Consider only the first paragraph.
    paragraph_end = help.find("\n\n")

    if paragraph_end != -1:
        help = help[:paragraph_end]  # noqa: A001

    # Collapse newlines, tabs, and spaces.
    words = help.split()

    if not words:
        return ""

    # The first paragraph started with a "no rewrap" marker, ignore it.
    if words[0] == "\b":
        words = words[1:]

    total_length = 0
    last_index = len(words) - 1

    for i, word in enumerate(words):
        total_length += len(word) + (i > 0)

        if total_length > max_length:  # too long, truncate
            break

        if word[-1] == ".":  # sentence end, truncate without "..."
            return " ".join(words[: i + 1])

        if total_length == max_length and i != last_index:
            break  # not at sentence end, truncate with "..."
    else:
        return " ".join(words)  # no truncation needed

    # Account for the length of the suffix.
    total_length += len("...")

    # remove words until the length is short enough
    while i > 0:
        total_length -= len(words[i]) + (i > 0)

        if total_length <= max_length:
            break

        i -= 1

    return " ".join(words[:i]) + "..."


class HelpFormatter:
    """This class helps with formatting text-based help pages.  It's
    usually just needed for very special internal cases, but it's also
    exposed so that developers can write their own fancy outputs.

    At present, it always writes into memory.

    :param indent_increment: the additional increment for each level.
    :param width: the width for the text.  This defaults to the terminal
                  width clamped to a maximum of 78.
    """

    def __init__(
        self,
        indent_increment: int = 2,
        width: int | None = None,
        max_width: int | None = None,
    ) -> None:
        self.indent_increment = indent_increment
        if max_width is None:
            max_width = 80
        if width is None:
            width = max(min(shutil.get_terminal_size().columns, max_width) - 2, 50)
        self.width = width
        self.current_indent = 0
        self.buffer: list[str] = []

    def write(self, string: str) -> None:
        """Writes a unicode string into the internal buffer."""
        self.buffer.append(string)

    def indent(self) -> None:
        """Increases the indentation."""
        self.current_indent += self.indent_increment

    def dedent(self) -> None:
        """Decreases the indentation."""
        self.current_indent -= self.indent_increment

    def write_usage(self, prog: str, args: str = "", prefix: str | None = None) -> None:
        """Writes a usage line into the buffer.

        :param prog: the program name.
        :param args: whitespace separated list of arguments.
        :param prefix: The prefix for the first line. Defaults to
            ``"Usage: "``.
        """
        if prefix is None:
            prefix = "Usage: "

        usage_prefix = f"{prefix:>{self.current_indent}}{prog} "
        text_width = self.width - self.current_indent

        if text_width >= (term_len(usage_prefix) + 20):
            # The arguments will fit to the right of the prefix.
            indent = " " * term_len(usage_prefix)
            self.write(
                wrap_text(
                    args,
                    text_width,
                    initial_indent=usage_prefix,
                    subsequent_indent=indent,
                )
            )
        else:
            # The prefix is too long, put the arguments on the next line.
            self.write(usage_prefix)
            self.write("\n")
            indent = " " * (max(self.current_indent, term_len(prefix)) + 4)
            self.write(
                wrap_text(
                    args, text_width, initial_indent=indent, subsequent_indent=indent
                )
            )

        self.write("\n")

    def write_heading(self, heading: str) -> None:
        """Writes a heading into the buffer."""
        self.write(f"{'':>{self.current_indent}}{heading}:\n")

    def write_paragraph(self) -> None:
        """Writes a paragraph into the buffer."""
        if self.buffer:
            self.write("\n")

    def write_text(self, text: str) -> None:
        """Writes re-indented text into the buffer.  This rewraps and
        preserves paragraphs.
        """
        indent = " " * self.current_indent
        self.write(
            wrap_text(
                text,
                self.width,
                initial_indent=indent,
                subsequent_indent=indent,
                preserve_paragraphs=True,
            )
        )
        self.write("\n")

    def write_dl(
        self,
        rows: Sequence[tuple[str, str]],
        col_max: int = 30,
        col_spacing: int = 2,
    ) -> None:
        """Writes a definition list into the buffer.  This is how options
        and commands are usually formatted.

        :param rows: a list of two item tuples for the terms and values.
        :param col_max: the maximum width of the first column.
        :param col_spacing: the number of spaces between the first and
                            second column.
        """
        rows = list(rows)
        widths = measure_table(rows)
        if len(widths) != 2:
            raise TypeError("Expected two columns for definition list")

        first_col = min(widths[0], col_max) + col_spacing

        for first, second in iter_rows(rows, len(widths)):
            self.write(f"{'':>{self.current_indent}}{first}")
            if not second:
                self.write("\n")
                continue
            if term_len(first) <= first_col - col_spacing:
                self.write(" " * (first_col - term_len(first)))
            else:
                self.write("\n")
                self.write(" " * (first_col + self.current_indent))

            text_width = max(self.width - first_col - 2, 10)
            wrapped_text = wrap_text(second, text_width, preserve_paragraphs=True)
            lines = wrapped_text.splitlines()

            if lines:
                self.write(f"{lines[0]}\n")

                for line in lines[1:]:
                    self.write(f"{'':>{first_col + self.current_indent}}{line}\n")
            else:
                self.write("\n")

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        """Helpful context manager that writes a paragraph, a heading,
        and the indents.

        :param name: the section name that is written as heading.
        """
        self.write_paragraph()
        self.write_heading(name)
        self.indent()
        try:
            yield
        finally:
            self.dedent()

    @contextmanager
    def indentation(self) -> Iterator[None]:
        """A context manager that increases the indentation."""
        self.indent()
        try:
            yield
        finally:
            self.dedent()

    def getvalue(self) -> str:
        """Returns the buffer contents."""
        return "".join(self.buffer)
