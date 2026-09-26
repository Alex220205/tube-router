"""Official line colours, which the TfL API does not serve."""

# From TfL's published design standards. These are the official hex values used on the
# tube map and in TfL's own products, keyed by the line id the Unified API uses.
LINE_COLOURS: dict[str, str] = {
    "bakerloo": "#B36305",
    "central": "#E32017",
    "circle": "#FFD300",
    "district": "#00782A",
    "hammersmith-city": "#F3A9BB",
    "jubilee": "#A0A5A9",
    "metropolitan": "#9B0056",
    "northern": "#000000",
    "piccadilly": "#003688",
    "victoria": "#0098D4",
    "waterloo-city": "#95CDBA",
}

# Used when TfL adds a line this table does not know about. Grey rather than something
# plausible-looking, so an unstyled line is obvious on the map instead of quietly wrong.
UNKNOWN_LINE_COLOUR = "#767676"
