"""Give the waiting-for-a-person records Odoo's activity support, so a task can be assigned with a reminder, a due date
and a notification (the standard Activities menu shows it too). No new columns: every activity field is computed."""
from odoo import models


class EiDailyOrderActivity(models.Model):
    _name = 'ei.daily.order'
    _inherit = ['ei.daily.order', 'mail.activity.mixin']


class EiBankImportActivity(models.Model):
    _name = 'ei.bank.import'
    _inherit = ['ei.bank.import', 'mail.activity.mixin']


class EiBankImportLineActivity(models.Model):
    _name = 'ei.bank.import.line'
    _inherit = ['ei.bank.import.line', 'mail.activity.mixin']


class EiParentStatementActivity(models.Model):
    _name = 'ei.parent.statement'
    _inherit = ['ei.parent.statement', 'mail.activity.mixin']


class EiParentStatementLineActivity(models.Model):
    _name = 'ei.parent.statement.line'
    _inherit = ['ei.parent.statement.line', 'mail.activity.mixin']


class EiLegacyCodeActivity(models.Model):
    _name = 'ei.legacy.code'
    _inherit = ['ei.legacy.code', 'mail.activity.mixin']


class EiFormulaActivity(models.Model):
    _name = 'ei.formula.definition'
    _inherit = ['ei.formula.definition', 'mail.activity.mixin']
