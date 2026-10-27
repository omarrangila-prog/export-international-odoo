"""The documents attached to a record (a scanned contract, a gate pass photo, the supplier's PDF, a bank statement file), listed for the
side-by-side viewer: the record stays on the left, the document is shown on the right, so a checker compares one with the other without
downloading anything. Only what the person may already read is listed: the record's own access rule decides."""
from odoo import _, api, models
from odoo.tools import format_datetime

PREVIEW = {'application/pdf': 'pdf', 'image/png': 'image', 'image/jpeg': 'image', 'image/gif': 'image', 'image/webp': 'image', 'image/svg+xml': 'image', 'text/plain': 'text'}


class EiDocuments(models.AbstractModel):
    _name = 'ei.documents'
    _description = "Documents attached to a record, for the side-by-side viewer"

    @api.model
    def list_for(self, model, res_id):
        if model not in self.env or not res_id:
            return []
        rec = self.env[model].browse(int(res_id)).exists()
        if not rec:
            return []
        rec.check_access('read')
        atts = self.env['ir.attachment'].sudo().search([('res_model', '=', model), ('res_id', '=', rec.id), ('res_field', '=', False)], order='create_date desc, id desc', limit=50)
        out = []
        for a in atts:
            kind = PREVIEW.get(a.mimetype or '', 'other')
            out.append(dict(
                id=a.id, name=a.name or _("Document"), mimetype=a.mimetype or '', kind=kind, size=a.file_size or 0,
                when=format_datetime(self.env, a.create_date, dt_format='dd MMM yyyy HH:mm') if a.create_date else '', who=a.create_uid.name or '',
                # plain links: they work only for a signed-in person who may read the record (no shareable access token is made)
                url=f"/web/content/{a.id}?download=false" if kind in ('pdf', 'text') else (f"/web/image/{a.id}" if kind == 'image' else ''),
                download=f"/web/content/{a.id}?download=true",
            ))
        return out
