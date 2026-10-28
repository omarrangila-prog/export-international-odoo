"""Ask, with a language model (Claude) behind it. Approved by the owner on 27 Oct 2026 (open decision 35).

Off until an administrator switches it on and a key is set. It is used only for questions the rule-based Ask did not understand
(and for questions written in Urdu). It never gets a way to change anything: its only tools are the rule-based answers and the
record search that already exist, run as the person asking, so it sees exactly what that person may see and nothing more. What it
sends to Anthropic is the question and those tool results. Its answer is shown with the records it used and is labelled as written
by a language model. Every question is logged with the engine that answered it.

Settings (Settings > Technical > System Parameters, administrator only):
  ei_assistant.llm_enabled     true to switch it on
  ei_assistant.llm_model       default claude-opus-5-5
  ei_assistant.ai_deps_path    where the Anthropic SDK is installed (default /opt/odoo-ai-deps, see HANDOVER.md)
The API key is read from the ANTHROPIC_API_KEY environment variable of the Odoo service (kept out of the database and its backups),
or else from the system parameter ei_assistant.anthropic_api_key.
"""
import json
import logging
import os
import sys

from odoo import api, models, _

from .assistant import _Denied, INTENT_PATTERNS

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'claude-opus-5-5'
DEFAULT_DEPS = '/opt/odoo-ai-deps'
MAX_TURNS = 6
TOPICS = {
    'help': "what Ask can answer",
    'work': "what is waiting for the person asking (their approvals and tasks)",
    'attention': "problems and alerts: duplicates, mismatches, differences, overdue approvals",
    'kpis': "the key figures of the person's Home page",
    'owed_to_us': "how much customers owe (open receivables), in total or for one customer named in the question",
    'overdue': "overdue customer invoices",
    'we_owe': "how much is owed to suppliers (open payables)",
    'lift': "material still to lift on delivery advices",
    'bank_todo': "bank statement lines still to check or match",
    'bank_balance': "bank balances in the books and as last confirmed by the bank",
}
SYSTEM = (
    "You answer questions from the staff of Export International, a steel trading company in Pakistan, about the records in their ERP. "
    "You can only read, through the tools given; you cannot approve, post, pay, send, change or delete anything, and you never say or "
    "imply that you did. Use the tools to get the facts; never invent a figure, a name or a document number. Every figure in your "
    "answer must come from a tool result. If the tools do not give the answer, say plainly what you could not find. If a tool says the "
    "person's role does not allow something, tell them that, and do not try to get the same facts another way. Amounts are in Pakistani "
    "rupees unless a tool says otherwise; quantities in MTL are metric tons. Answer in the language of the question (English or Urdu), "
    "in at most five short sentences, without headings; the records you used are shown below your answer, so do not repeat whole tables."
)


class EiAssistant(models.AbstractModel):
    _inherit = 'ei.assistant'

    # ------------------------------------------------------------------ configuration
    def _llm_param(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_str(key, default)

    def _llm_key(self):
        return os.environ.get('ANTHROPIC_API_KEY') or self._llm_param('ei_assistant.anthropic_api_key') or ''

    def _llm_sdk(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            path = self._llm_param('ei_assistant.ai_deps_path', DEFAULT_DEPS)
            if not (path and os.path.isdir(path)):
                return None
            if path not in sys.path:
                sys.path.append(path)                 # appended: never shadows the packages Odoo itself runs on
            try:
                import anthropic  # noqa: F401
            except ImportError:
                return None
        import anthropic
        return anthropic

    def _llm_client(self):
        sdk = self._llm_sdk()
        return sdk.Anthropic(api_key=self._llm_key(), timeout=90.0, max_retries=2) if sdk else None

    @api.model
    def llm_status(self):
        """For the administrator: is the language model on, and if not, why not. Never returns the key."""
        on = self.env['ir.config_parameter'].sudo().get_bool('ei_assistant.llm_enabled', False)
        return {'enabled': on, 'key_set': bool(self._llm_key()), 'sdk': bool(self._llm_sdk()),
                'model': self._llm_param('ei_assistant.llm_model', DEFAULT_MODEL)}

    def _llm_available(self):
        s = self.llm_status()
        return s['enabled'] and s['key_set'] and s['sdk']

    # ------------------------------------------------------------------ the tools: existing read-only answers, as the person asking
    def _llm_tools(self):
        topics = [k for k, _p in INTENT_PATTERNS if self._can_use(k)]
        tools = [{
            'name': 'find_records', 'strict': True,
            'description': "Search the records this person may read by names, document numbers or old (FoxPro) codes. "
                           "Returns a summary of one matching party or document, or a list of matches.",
            'input_schema': {'type': 'object', 'properties': {'words': {'type': 'string', 'description': "names, numbers or codes to look for"}},
                             'required': ['words'], 'additionalProperties': False},
        }]
        if topics:
            tools.append({
                'name': 'standard_answer', 'strict': True,
                'description': "Get one of the standard answers, worked out from the posted records for this person. Topics: "
                               + '; '.join('%s = %s' % (k, TOPICS[k]) for k in topics) + ". "
                               "Pass the person's question too, so a customer named in it is used.",
                'input_schema': {'type': 'object', 'properties': {
                    'topic': {'type': 'string', 'enum': topics}, 'question': {'type': 'string'}},
                    'required': ['topic', 'question'], 'additionalProperties': False},
            })
        return tools

    def _llm_run_tool(self, name, args):
        """-> (reply or None, text for the model). Exceptions that mean 'not allowed' are told to the model as such."""
        try:
            if name == 'find_records':
                reply = self._by_words(str(args.get('words') or ''))
            elif name == 'standard_answer' and args.get('topic') in TOPICS and self._can_use(args['topic']):
                reply = getattr(self, '_h_' + args['topic'])(str(args.get('question') or ''))
            else:
                return None, "This topic is not available to the person asking."
        except _Denied as e:
            return None, "Not allowed for this person's role: %s" % e
        return reply, self._llm_reply_text(reply)

    @staticmethod
    def _llm_reply_text(reply):
        out = [reply.get('title') or '']
        for b in reply.get('blocks') or []:
            if b['type'] == 'text':
                out.append(b['text'])
            elif b['type'] == 'figures':
                out += ['%s: %s%s' % (i.get('label'), i.get('value'), (' (%s)' % i['note']) if i.get('note') else '') for i in b.get('items') or []]
            elif b['type'] == 'list':
                out += ['- %s %s' % (i.get('text'), i.get('sub') or '') for i in b.get('items') or []]
            elif b['type'] == 'table':
                out.append(' | '.join(map(str, b.get('columns') or [])))
                out += [' | '.join(map(str, r.get('cells') or [])) for r in b.get('rows') or []]
                if b.get('more'):
                    out.append(b['more'])
        if reply.get('how'):
            out.append('How it is worked out: %s' % reply['how'])
        return '\n'.join(str(x) for x in out if x)

    # ------------------------------------------------------------------ the conversation with the model
    def _llm_answer(self, question):
        client = self._llm_client()
        if client is None:
            return None
        sdk = self._llm_sdk()
        model = self._llm_param('ei_assistant.llm_model', DEFAULT_MODEL)
        tools = self._llm_tools()
        messages = [{'role': 'user', 'content': question}]
        used = []
        try:
            for _turn in range(MAX_TURNS):
                resp = client.beta.messages.create(
                    model=model, max_tokens=4000, system=SYSTEM, tools=tools, messages=messages,
                    output_config={'effort': 'low'},
                    betas=['server-side-fallback-2026-07-01'], fallbacks='default')
                if resp.stop_reason == 'refusal':
                    return None
                calls = [b for b in resp.content if b.type == 'tool_use']
                if resp.stop_reason != 'tool_use' or not calls:
                    text = '\n'.join(b.text for b in resp.content if b.type == 'text').strip()
                    return self._llm_envelope(text, used, model) if text else None
                messages.append({'role': 'assistant', 'content': resp.content})
                results = []
                for c in calls:
                    args = c.input if isinstance(c.input, dict) else {}
                    reply, text = self._llm_run_tool(c.name, args)
                    if reply:
                        used.append(reply)
                    results.append({'type': 'tool_result', 'tool_use_id': c.id, 'content': text[:20000], 'is_error': reply is None})
                messages.append({'role': 'user', 'content': results})
        except sdk.APIStatusError as e:
            _logger.warning("Ask: the language model returned %s; the rule-based answer is shown instead.", e.status_code)
        except sdk.APIConnectionError:
            _logger.warning("Ask: the language model could not be reached; the rule-based answer is shown instead.")
        return None

    def _llm_envelope(self, text, used, model):
        """The model's words on top, then the very records it used (tables, figures, links), each with its own sources."""
        blocks, sources = [{'type': 'text', 'text': text}], []
        for reply in used:
            offset = len(sources)
            sources += reply.get('sources') or []
            for b in reply.get('blocks') or []:
                b = json.loads(json.dumps(b))
                for holder in (b.get('items') or []) + (b.get('rows') or []):
                    if isinstance(holder, dict) and holder.get('src') is not None:
                        holder['src'] += offset
                blocks.append(b)
        return self._reply('llm', _("Answer"), blocks, sources,
                           _("Written by a language model (%s) from the records shown below, read with your own rights. It cannot change anything. "
                             "Check any figure against the records before acting on it.", model))

    @api.model
    def ask(self, question):
        question = (question or '').strip()
        reply = self._answer(question)
        engine = 'rules'
        if reply['kind'] == 'unknown' and self.env.user.has_group('ei_legacy_master.group_ei_user') and self._llm_available():
            better = self._llm_answer(question)
            if better:
                reply, engine = better, 'llm'
        self._log(question, reply, engine)
        return reply

    def _log(self, question, reply, engine='rules'):
        super()._log(question, reply)
        last = self.env['ei.assistant.log'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)
        if last and engine != 'rules':
            last.engine = engine
