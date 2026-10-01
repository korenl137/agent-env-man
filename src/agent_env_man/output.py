"""Plain-text presentation of command reports without dropping nested details."""


def format_report(report):
    """Render reports as indented fields and lists, preserving multiline values."""
    lines = []

    def scalar(value):
        if value is None:
            return "none"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    def render(value, indent=0, label=None):
        prefix = " " * indent
        heading = "-" if label == "-" else f"{label}:" if label is not None else ""
        if isinstance(value, (dict, list)) and value:
            if heading:
                lines.append(prefix + heading)
                indent += 2
                prefix = " " * indent
            if isinstance(value, dict):
                for key, child in value.items():
                    render(child, indent, str(key).replace("_", " "))
            else:
                for child in value:
                    if isinstance(child, (dict, list)) and child:
                        start = len(lines)
                        render(child, indent + 2)
                        lines[start] = prefix + "- " + lines[start][indent + 2:]
                    else:
                        render(child, indent, "-")
        else:
            text = "none" if isinstance(value, (dict, list)) else scalar(value)
            parts = text.split("\n")
            separator = " " if heading else ""
            # Align continuation lines with the value, so errors/notices remain
            # readable without looking like additional report fields.
            lead = prefix + heading + separator
            lines.append(lead + parts[0])
            lines.extend(" " * len(lead) + part for part in parts[1:])

    render(report)
    return "\n".join(lines)
