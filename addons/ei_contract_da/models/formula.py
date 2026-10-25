import json
import re
from decimal import Decimal, InvalidOperation

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from . import formula_engine as fe


class EiFormulaDefinition(models.Model):
    _name = 'ei.formula.definition'
    _description = 'Formula definition (versioned, accountant-approved)'
    _inherit = ['mail.thread']
    _order = 'code, version desc'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    version = fields.Integer(required=True, default=1, readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('retired', 'Retired')],
                             default='draft', readonly=True, tracking=True, index=True)
    owner_id = fields.Many2one('res.users', string='Business owner', default=lambda s: s.env.user)
    rationale = fields.Text(required=True, help="Why this rule exists and where it comes from (document, clause).")
    rounding_mode = fields.Selection([('final_only', 'Round only the reported results'),
                                      ('each_step', 'Round every step')], required=True,
                                     help="Not established by the source documents; the accountant decides.")
    effective_from = fields.Date()
    effective_to = fields.Date()
    step_ids = fields.One2many('ei.formula.step', 'definition_id')
    test_ids = fields.One2many('ei.formula.test', 'definition_id')
    param_keys = fields.Char(compute='_compute_param_keys')
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)
    supersedes_id = fields.Many2one('ei.formula.definition', readonly=True)
    company_id = fields.Many2one('res.company', help="Empty = shared by all companies (default).")

    _code_version = models.Constraint('unique(code, version)', 'This formula code already has that version.')

    @api.depends('step_ids.param')
    def _compute_param_keys(self):
        for r in self:
            r.param_keys = ', '.join(sorted({s.param for s in r.step_ids}))

    def _steps(self):
        return [{'key': s.key, 'kind': s.kind, 'base_ref': s.base_ref, 'param': s.param}
                for s in self.step_ids.sorted('sequence')]

    def compute(self, basic_rate, quantity=1, params=None, places=2):
        self.ensure_one()
        return fe.evaluate(self._steps(), basic_rate, quantity, params, places, self.rounding_mode)

    def write(self, vals):
        guarded = set(vals) - {'owner_id', 'message_follower_ids'}
        if guarded and any(r.state != 'draft' for r in self) and not (set(vals) <= {'state', 'approved_by', 'approved_at'}):
            raise UserError(_("An approved formula is immutable; create a new version instead."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft formulas can be deleted."))
        return super().unlink()

    def run_tests(self):
        self.ensure_one()
        return [(t, t.passes) for t in self.test_ids]

    def action_approve(self):
        if not self.env.user.has_group('ei_contract_da.group_ei_formula_approver'):
            raise AccessError(_("Only a formula approver (accountant) can approve a formula."))
        for r in self:
            if r.state != 'draft':
                raise UserError(_("Only a draft can be approved."))
            if r.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("The author of a formula cannot approve it."))
            if not r.step_ids or not r.test_ids:
                raise UserError(_("A formula needs at least one step and one signed test case."))
            failed = [t.name for t, ok in r.run_tests() if not ok]
            if failed:
                raise UserError(_("Test cases fail: %s", ', '.join(failed)))
            r.write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_at': fields.Datetime.now()})
            # older approved versions of the same code are retired for NEW use; contracts keep their snapshots
            self.search([('code', '=', r.code), ('id', '!=', r.id), ('state', '=', 'approved')]).write({'state': 'retired'})

    def action_new_version(self):
        self.ensure_one()
        top = self.search([('code', '=', self.code)], order='version desc', limit=1)
        new = self.copy({'name': self.name, 'version': top.version + 1, 'state': 'draft', 'supersedes_id': self.id,
                         'approved_by': False, 'approved_at': False})
        for s in self.step_ids:
            s.copy({'definition_id': new.id})
        for t in self.test_ids:
            t.copy({'definition_id': new.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id, 'view_mode': 'form'}

    def action_retire(self):
        if not self.env.user.has_group('ei_contract_da.group_ei_formula_approver'):
            raise AccessError(_("Only a formula approver can retire a formula."))
        self.filtered(lambda r: r.state == 'approved').write({'state': 'retired'})


class EiFormulaStep(models.Model):
    _name = 'ei.formula.step'
    _description = 'Formula step'
    _order = 'definition_id, sequence, id'

    definition_id = fields.Many2one('ei.formula.definition', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    key = fields.Char('Result name', required=True, help="e.g. mill_rate. Later steps can use it as their base.")
    kind = fields.Selection([(k, '%s: %s' % (k, v)) for k, v in fe.KINDS.items()], required=True)
    base_ref = fields.Char('Works on', required=True, default='basic_rate',
                           help="'basic_rate' or the result name of an earlier step.")
    param = fields.Char('Parameter', required=True, help="Name of the rate supplied on each contract line, e.g. deduction_pct.")

    _uniq = models.Constraint('unique(definition_id, key)', 'Result names must be unique within a formula.')

    @api.constrains('key', 'param', 'base_ref')
    def _check_names(self):
        for s in self:
            for v in (s.key, s.param, s.base_ref):
                if not re.fullmatch(r'[a-z][a-z0-9_]*', v or ''):
                    raise UserError(_("Names must be lower-case identifiers (got %r).", v))
            if s.key == 'basic_rate':
                raise UserError(_("'basic_rate' is reserved."))

    @api.model_create_multi
    def create(self, vals_list):
        self._guard(vals_list)
        return super().create(vals_list)

    def _guard(self, vals_list):
        for v in vals_list:
            d = self.env['ei.formula.definition'].browse(v.get('definition_id'))
            if d and d.state != 'draft':
                raise UserError(_("The formula is %s; its steps are locked.", d.state))

    def write(self, vals):
        if any(r.definition_id.state != 'draft' for r in self) and not self.env.context.get('ei_formula_copy'):
            raise UserError(_("The formula is not a draft; its steps are locked."))
        return super().write(vals)

    def unlink(self):
        if any(r.definition_id.state != 'draft' for r in self):
            raise UserError(_("The formula is not a draft; its steps are locked."))
        return super().unlink()


class EiFormulaTest(models.Model):
    _name = 'ei.formula.test'
    _description = 'Signed test case of a formula'

    definition_id = fields.Many2one('ei.formula.definition', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True)
    basic_rate = fields.Float(required=True, digits=(16, 4))
    quantity = fields.Float(default=1.0, digits=(16, 4))
    params_json = fields.Char('Parameters (JSON)', required=True, default='{}',
                              help='e.g. {"deduction_pct": "1.32"}; write numbers as strings to keep them exact.')
    expected_key = fields.Char(required=True)
    expected_value = fields.Char(required=True, help="Exact expected result, e.g. 207228.00")
    actual_value = fields.Char(compute='_compute_result')
    passes = fields.Boolean(compute='_compute_result')

    @api.depends('definition_id.step_ids', 'definition_id.rounding_mode', 'basic_rate', 'quantity',
                 'params_json', 'expected_key', 'expected_value')
    def _compute_result(self):
        for t in self:
            try:
                params = json.loads(t.params_json or '{}')
                _rows, values = t.definition_id.compute(Decimal(str(t.basic_rate)), Decimal(str(t.quantity)), params)
                actual = values.get(t.expected_key)
                t.actual_value = str(actual) if actual is not None else 'n/a'
                t.passes = actual is not None and actual == Decimal(t.expected_value)
            except (fe.FormulaError, ValueError, InvalidOperation, TypeError) as e:
                t.actual_value = 'error: %s' % e
                t.passes = False

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            d = self.env['ei.formula.definition'].browse(v.get('definition_id'))
            if d and d.state != 'draft':
                raise UserError(_("The formula is %s; its tests are locked.", d.state))
        return super().create(vals_list)

    def write(self, vals):
        if any(r.definition_id.state != 'draft' for r in self):
            raise UserError(_("The formula is not a draft; its tests are locked."))
        return super().write(vals)

    def unlink(self):
        if any(r.definition_id.state != 'draft' for r in self):
            raise UserError(_("The formula is not a draft; its tests are locked."))
        return super().unlink()
