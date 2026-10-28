"""What was asked and whether it could be answered. Read by management and the auditor only, so they can see which questions
people really have (and which ones the assistant cannot answer yet). The answer itself is not stored: it can always be asked again."""
from odoo import fields, models


class EiAssistantLog(models.Model):
    _name = 'ei.assistant.log'
    _description = 'A question asked of the assistant'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', 'Asked by', required=True, readonly=True, index=True, ondelete='cascade')
    question = fields.Char(readonly=True)
    intent = fields.Char('Understood as', readonly=True)
    outcome = fields.Selection([('answered', 'Answered'), ('choose', 'Asked which one'), ('unknown', 'Not understood'),
                                ('denied', 'Not allowed for this role'), ('refused', 'Asked to change something')], readonly=True, index=True)
    engine = fields.Selection([('rules', 'Rule-based'), ('llm', 'Language model')], 'Answered by', default='rules', readonly=True, index=True)
