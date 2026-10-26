def migrate(cr, version):
    """1.0 stored a salted hash per person (to be typed with a user name); 1.1 stores a keyed index so a PIN alone can say who it is.
    A hash cannot be converted (the PIN is not stored), so the first version's PINs are cleared and must be set again."""
    cr.execute("DROP TABLE IF EXISTS ei_pin_credential CASCADE")
