##############################################################################
#
#    Copyright (C) 2014 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Cyril Sester <csester@compassion.ch>
#
#    The licence is in the file __manifest__.py
#
##############################################################################

import logging

from datetime import datetime, date

import odoo.addons.decimal_precision as dp
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RecurringContract(models.Model):
    """ A contract to perform recurring invoicing to a partner """

    _name = "recurring.contract"
    _description = "Recurring contract"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'utm.mixin']
    _rec_name = 'reference'
    _order = "create_date desc"

    ##########################################################################
    #                                 FIELDS                                 #
    ##########################################################################

    reference = fields.Char(
        default="/", required=True, readonly=True,
        states={'draft': [('readonly', False)]}, copy=False)
    start_date = fields.Datetime(
        readonly=True, states={'draft': [('readonly', False)]},
        copy=False, track_visibility="onchange")
    end_date = fields.Datetime(
        readonly=False, states={'terminated': [('readonly', True)]},
        track_visibility="onchange", copy=False)
    end_reason_id = fields.Many2one(
        'recurring.contract.end.reason', 'End reason', copy=False,
        ondelete='restrict', readonly=False
    )
    next_invoice_date = fields.Date(
        readonly=False, states={'draft': [('readonly', False)]},
        default=lambda c: c._default_next_invoice_date(),
        track_visibility="onchange")
    last_paid_invoice_date = fields.Date(
        compute='_compute_last_paid_invoice')
    partner_id = fields.Many2one(
        'res.partner', 'Partner', required=True, readonly=True,
        states={'draft': [('readonly', False)]}, ondelete='restrict',
        index=True
    )
    group_id = fields.Many2one(
        'recurring.contract.group', 'Payment Options',
        required=True, ondelete='set null', track_visibility="onchange", readonly=False)
    invoice_line_ids = fields.One2many(
        'account.invoice.line', 'contract_id',
        'Related invoice lines', readonly=True, copy=False)
    contract_line_ids = fields.One2many(
        'recurring.contract.line', 'contract_id',
        'Contract lines', track_visibility="onchange", copy=True, readonly=False)
    state = fields.Selection(
        [
            ('draft', _('Draft')),
            ('waiting', _('Waiting Payment')),
            ('active', _('Active')),
            ('terminated', _('Terminated')),
            ('cancelled', _('Cancelled'))
        ], default='draft', readonly=True,
        track_visibility='onchange', copy=False, index=True)
    total_amount = fields.Float(
        'Total', compute='_compute_total_amount',
        digits=dp.get_precision('Account'),
        track_visibility="onchange", store=True)
    payment_mode_id = fields.Many2one(
        'account.payment.mode', string='Payment mode',
        related='group_id.payment_mode_id', readonly=True, store=True)
    nb_invoices = fields.Integer(compute='_compute_invoices')
    activation_date = fields.Datetime(readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company',
        'Company',
        required=True,
        default=lambda self: self.env.user.company_id.id, readonly=False
    )
    comment = fields.Text()

    _sql_constraints = [
        ('unique_ref', "unique(reference)", "Reference must be unique!")
    ]

    ##########################################################################
    #                             FIELDS METHODS                             #
    ##########################################################################
    @api.depends('contract_line_ids', 'contract_line_ids.amount',
                 'contract_line_ids.quantity')
    def _compute_total_amount(self):
        for contract in self:
            contract.total_amount = sum([
                line.subtotal for line in contract.contract_line_ids
            ])

    def _compute_last_paid_invoice(self):
        for contract in self:
            contract.last_paid_invoice_date = max(
                [invl.invoice_id.date_invoice for invl in
                 contract.invoice_line_ids if invl.state == 'paid'] or [False])

    def _compute_invoices(self):
        for contract in self:
            contract.nb_invoices = len(
                contract.mapped('invoice_line_ids.invoice_id').filtered(
                    lambda i: i.state not in ('cancel', 'draft')
                ))

    @api.model
    def _default_next_invoice_date(self):
        # set the next invoice for the current month if we are earlier than the 15th
        # otherwise set it to the next month
        today = datetime.today()
        month_delta = relativedelta(months=0 if today.day < 15 else 1)
        next_invoice = today.replace(day=1) + month_delta
        return next_invoice.date()

    ##########################################################################
    #                              ORM METHODS                               #
    ##########################################################################

    @api.model
    def create(self, vals):
        """ Add a sequence generated ref if none is given """
        if vals.get('reference', '/') == '/':
            vals['reference'] = self.env['ir.sequence'].next_by_code(
                'recurring.contract.ref')

        return super().create(vals)

    @api.multi
    def write(self, vals):
        """ Perform various checks when a contract is modified. """
        if vals.get('next_invoice_date') and not self.env.context.get(
                "no_clean_on_write", False):
            self._on_change_next_invoice_date(vals['next_invoice_date'])

        res = super().write(vals)

        clean_is_done = False
        if "partner_id" in vals:
            self.mapped("group_id").write({"partner_id": vals["partner_id"]})
            clean_is_done = "clean_invoices" in self.mapped("group_id.change_method")

        if 'contract_line_ids' in vals and not clean_is_done:
            self._on_contract_lines_changed()
            clean_is_done = True

        if ("group_id" in vals or "partner_id" in vals) and not clean_is_done:
            self.group_id.clean_invoices()

        return res

    @api.multi
    def copy(self, default=None):
        for contract in self:
            default = default or dict()
            # Put next_invoice_date after last_paid_date when copying contract
            if contract.last_paid_invoice_date:
                last_paid_invoice = contract.last_paid_invoice_date
                next_invoice_date = last_paid_invoice + relativedelta(months=1)
            else:
                # If it wasn't paid, put it this month (same day as before)
                today = datetime.today()
                next_invoice_date = contract.next_invoice_date
                next_invoice_date = next_invoice_date.replace(
                    month=today.month, year=today.year)
            default['next_invoice_date'] = next_invoice_date
        return super().copy(default)

    @api.multi
    def unlink(self):
        if self.filtered('start_date'):
            raise UserError(
                _('You cannot delete a validated contract.'))
        return super().unlink()

    ##########################################################################
    #                             PUBLIC METHODS                             #
    ##########################################################################
    @api.multi
    def clean_invoices(self, since_date=None, to_date=None, clean_invoices_paid=False,
                       keep_lines=False):
        """ By default, launch asynchronous job to perform the task.
            Context value async_mode set to False can force to perform
            the task immediately.
        """
        if self.env.context.get('async_mode', True):
            self.with_delay()._clean_invoices(
                since_date, to_date, clean_invoices_paid, keep_lines)
        else:
            self._clean_invoices(since_date, to_date, clean_invoices_paid, keep_lines)

    def rewind_next_invoice_date(self):
        """ Rewinds the next invoice date. rewind date will be between today and the
        newest opened invoice date. latest paid invoice date if exist else earliest
        open one (starting from today)
        all invoices after rewind date will be cleaned
        """
        res = self.env["account.invoice"]

        for contract in self:
            if contract.state not in ["terminated", "cancelled"]:
                # if paid invoice exist in range next_invoice should be *after*
                # latest paid invoice
                latest_paid_invoice_date = max(
                    contract.invoice_line_ids.filter_for_contract_rewind("paid")
                    .mapped("invoice_id.date_invoice") or [False]
                )

                # if there is only open invoice we are looking for the
                # oldest one (within the range)
                earliest_open_invoice_date = min(
                    contract.invoice_line_ids.filter_for_contract_rewind("open")
                    .mapped("invoice_id.date_invoice") or [False])

                rewind_invoice_date = latest_paid_invoice_date + \
                    contract.group_id.get_relative_delta() \
                    if latest_paid_invoice_date else earliest_open_invoice_date

                if rewind_invoice_date:
                    res |= contract._clean_invoices(rewind_invoice_date)
                    contract.with_context(no_clean_on_write=True).write({
                        "next_invoice_date": rewind_invoice_date
                    })
                else:
                    # No open/paid invoices, look for cancelled ones
                    rewind_invoice_date = min(
                        contract.invoice_line_ids.filter_for_contract_rewind("cancel")
                        .mapped("invoice_id.date_invoice") or [False]
                    )

                    if rewind_invoice_date:
                        res |= contract._clean_invoices(rewind_invoice_date)
                        contract.with_context(no_clean_on_write=True).write({
                            "next_invoice_date": rewind_invoice_date
                        })

        return res

    def update_next_invoice_date(self):
        """ Recompute and set next_invoice date. """
        for contract in self:
            next_date = contract._compute_next_invoice_date()
            contract.write({'next_invoice_date': next_date})
        return True

    @api.multi
    def get_inv_lines_data(self):
        """ Setup a dict with data passed to invoice_line.create.
        If any custom data is wanted in invoice line from contract,
        just inherit this method.
        :return: list of dictionaries
        """
        res = list()
        default_account = self.env['account.invoice.line']._default_account()
        for contract_line in self.mapped('contract_line_ids'):
            product = contract_line.product_id
            inv_line_data = {
                'name': product.name,
                'price_unit': contract_line.amount,
                'quantity': contract_line.quantity,
                'product_id': product.id,
                'contract_id': contract_line.contract_id.id,
                'account_id': product.property_account_income_id.id or
                default_account
            }
            res.append(inv_line_data)
        return res

    ##########################################################################
    #                             VIEW CALLBACKS                             #
    ##########################################################################
    @api.onchange('partner_id')
    def on_change_partner_id(self):
        """ On partner change, we update the group_id. If partner has
        only 1 group, we take it. Else, we take nothing.
        """
        group_ids = self.env['recurring.contract.group'].search(
            [('partner_id', '=', self.partner_id.id)])
        if len(group_ids) == 1:
            self.group_id = group_ids
        else:
            self.group_id = False
        if self.partner_id.company_id:
            self.company_id = self.partner_id.company_id

    @api.multi
    def button_generate_invoices(self):
        """ Immediately generate invoices of the contract group. """
        return self.mapped('group_id').with_context(
            async_mode=False).generate_invoices()

    @api.multi
    def open_invoices(self):
        self.ensure_one()
        invoice_ids = self.mapped('invoice_line_ids.invoice_id').ids
        return {
            'name': _('Contract invoices'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('account.invoice_tree').id, 'tree'),
                (self.env.ref('account.invoice_form').id, 'form'),
            ],
            'res_model': 'account.invoice',
            'domain': [('id', 'in', invoice_ids)],
            'context': self.with_context(
                form_view_ref='account.invoice_form',
                search_default_invoices=True
            ).env.context,
            'target': 'current',
        }

    ##########################################################################
    #                            WORKFLOW METHODS                            #
    ##########################################################################
    @api.multi
    def contract_draft(self):
        if self.filtered(lambda c: c.state == 'active'):
            raise UserError(_("Active contract cannot be put to draft"))
        self.write({'state': 'draft'})
        return True

    @api.multi
    def contract_waiting(self):
        if self.filtered(lambda c: c.state == 'active'):
            raise UserError(_("Active contract cannot be put to waiting"))
        if self.filtered(lambda c: not c.total_amount):
            raise UserError(_("Please configure contract lines"))
        return self.write({
            'state': 'waiting',
            'start_date': fields.Datetime.now()
        })

    @api.multi
    def contract_active(self):
        if self.filtered(lambda c: c.state != 'waiting'):
            raise UserError(_('Only validated contracts can be activated.'))
        self.write({
            'state': 'active',
            'activation_date': fields.Datetime.now(),
        })
        return True

    @api.multi
    def action_contract_terminate(self):
        """
        Action for finishing a contract. It will go in either 'terminated'
        or 'cancelled' state depending if it was active or not.
        :return: True
        """
        active_contracts = self.filtered('activation_date')
        if active_contracts:
            active_contracts.contract_terminated()
        inactive = self - active_contracts
        if inactive:
            inactive.contract_cancelled()
        return True

    @api.multi
    def contract_terminated(self):
        now = fields.Datetime.now()
        self.write({
            'state': 'terminated',
            'end_date': now
        })
        self.clean_invoices(now, clean_invoices_paid=True)
        return True

    @api.multi
    def contract_cancelled(self):
        today = fields.Datetime.now()
        self.write({
            'state': 'cancelled',
            'end_date': today
        })
        self.clean_invoices(today, clean_invoices_paid=True)
        return True

    @api.multi
    def action_cancel_draft(self):
        """ Set back a cancelled contract to draft state. """
        if self.filtered(lambda c: c.state != 'cancelled'):
            raise UserError(_("Only cancelled contracts can be set back to "
                              "draft."))
        self.write({
            'state': 'draft',
            'end_date': False,
            'activation_date': False,
            'next_invoice_date': self._default_next_invoice_date(),
            'start_date': False,
            'end_reason_id': False
        })
        return True

    @api.multi
    def force_activation(self):
        """ Used to transition contracts in active state. """
        self.filtered(lambda c: c.state == 'draft').contract_waiting()
        self.contract_active()
        return True

    @api.multi
    def invoice_unpaid(self, invoice):
        """ Hook when invoice is unpaid """
        pass

    @api.multi
    def invoice_paid(self, invoice):
        """ Activate contract if it is waiting for payment. """
        activate_contracts = self.filtered(lambda c: c.state == 'waiting')
        if activate_contracts:
            activate_contracts.contract_active()

    @api.model
    def end_date_reached(self):
        now = fields.Datetime.now()
        expired = self.search([
            ('end_date', '>=', now),
            ('state', 'not in', ['cancelled', 'terminated'])
        ])
        return expired.action_contract_terminate()

    def clean_invoices_paid(self, since_date, to_date):
        """
        Unreconcile paid invoices in the given period, so that they
        can be cleaned with the clean_invoices process.
        :param since_date: clean invoices with date greater than this
        :param to_date: clean invoices with date lower than this
        :return: invoices cleaned that contained other contracts than the
                 the ones we are cleaning.
        """
        # Find all paid invoice lines after the given date
        inv_line_obj = self.env['account.invoice.line']
        invl_search = self._filter_clean_invoices(since_date, to_date)
        inv_lines = inv_line_obj.search(invl_search)
        move_lines = inv_lines.mapped('invoice_id.move_id.line_ids').filtered(
            'reconciled')
        reconciles = inv_lines.mapped(
            'invoice_id.payment_move_line_ids.full_reconcile_id')

        # Unreconcile paid invoices
        move_lines |= reconciles.mapped('reconciled_line_ids')
        move_lines.remove_move_reconcile()

        return move_lines.mapped('invoice_id.invoice_line_ids').filtered(
            lambda l: l.contract_id not in self).mapped('invoice_id')

    ##########################################################################
    #                             PRIVATE METHODS                            #
    ##########################################################################
    @api.multi
    def _clean_invoices(self, since_date=None, to_date=None, clean_invoices_paid=False,
                        keep_lines=False):
        """ Clean invoices
        This method deletes invoices lines generated for a given contract
        having a due date >= current month. If the invoice_line was the
        only line in the invoice, we cancel the invoice. In the other
        case, we have to revalidate the invoice to update the move lines.

        When the sponsor has paid in advance, we cancel/modify the paid
        invoices and let the user decide what to do with the payment.

        :param since_date: optional date from which invoices will be cleaned
        :param to_date: optional date limit for invoices we want to clean
        :param clean_invoices_paid: set to true to unreconcile paid invoices
                                    and clean them as well.
        :param keep_lines: set to true to avoid deleting invoice lines
        :return: invoices cleaned (which should be in cancel state)
        """
        _logger.info("clean invoices called.")
        if isinstance(since_date, (date, datetime)):
            since_date = fields.Date.to_string(since_date)
        if isinstance(to_date, (date, datetime)):
            to_date = fields.Date.to_string(to_date)
        if clean_invoices_paid:
            paid_invoices = self.clean_invoices_paid(since_date, to_date)
        inv_lines = self._get_invoice_lines_to_clean(since_date, to_date)
        invoices = inv_lines.mapped('invoice_id')
        empty_invoices = self.env['account.invoice']
        to_remove_invl = self.env['account.invoice.line']

        for inv_line in inv_lines:
            invoice = inv_line.invoice_id
            # Check if invoice is empty after removing the invoice_lines
            # of the given contract
            if invoice not in empty_invoices:
                remaining_lines = invoice.invoice_line_ids.filtered(
                    lambda l: not l.contract_id or l.contract_id not in self)
                if remaining_lines and not keep_lines:
                    # We can move or remove the line
                    to_remove_invl |= inv_line
                else:
                    # The invoice would be empty if we remove the line
                    empty_invoices |= invoice

        invoices.action_invoice_cancel()
        renew_invs = invoices - empty_invoices
        renew_invs.action_invoice_draft()
        invoices.env.clear()
        to_remove_invl.unlink()

        # Invoices to set back in open state
        self.env.clear()
        renew_invs.action_invoice_open()
        self.env.clear()

        if clean_invoices_paid:
            paid_invoices.reconcile_after_clean()

        _logger.info(str(len(invoices)) + " invoices cleaned.")
        return invoices

    def _on_contract_lines_changed(self):
        """Update related invoices to reflect the changes to the contract.
        """
        lock_date = self.mapped("company_id")[:1].period_lock_date
        invl_search = [
            ('contract_id', 'in', self.ids),
            ('state', 'not in', ('paid', 'cancel'))]
        if lock_date:
            invl_search.append(("due_date", ">", fields.Date.to_string(lock_date)))
        inv_lines = self.env['account.invoice.line'].search(invl_search)
        invoices = inv_lines.mapped('invoice_id')
        invoices.action_invoice_cancel()
        invoices.action_invoice_draft()
        invoices.env.clear()
        if self._update_invoice_lines(invoices):
            invoices.action_invoice_open()

    def _compute_next_invoice_date(self):
        """ Compute next_invoice_date for a single contract. """
        next_date = self.next_invoice_date
        next_date += self.group_id.get_relative_delta()
        return next_date

    def _update_invoice_lines(self, invoices):
        """Update invoice lines generated by a contract, when the contract
        was modified and corresponding invoices were cancelled.

        Parameters:
            - invoice_ids (list): ids of draft invoices to be
                                  updated and validated
        Returns:
            - True if all writes were successful, False otherwise
        """
        success = True
        for contract in self:
            # Update payment term
            invoices.write({
                'payment_mode_id': contract.payment_mode_id.id
            })

            for invoice in invoices:
                # Generate new invoice_lines
                old_lines = invoice.invoice_line_ids.filtered(
                    lambda line: line.contract_id.id == contract.id)
                old_lines.unlink()
                journal = invoice.journal_id
                invl = [(0, 0, l) for l in
                        contract.with_context(
                            journal_id=journal.id).get_inv_lines_data() if l]
                if invl:
                    invoice.write({'invoice_line_ids': invl})
                else:
                    success = False
        return success

    def _on_change_next_invoice_date(self, new_invoice_date):
        for contract in self:
            new_invoice_date = fields.Date.from_string(new_invoice_date)
            if contract.next_invoice_date:
                next_invoice_date = contract.next_invoice_date
                if next_invoice_date > fields.Date.to_date(new_invoice_date):
                    # Cancel invoices after new_invoice_date
                    contract.clean_invoices(new_invoice_date)
        return True

    def _get_invoice_lines_to_clean(self, since_date, to_date):
        """ Find all unpaid invoice lines in the given period. """
        invl_search = [('contract_id', 'in', self.ids),
                       ('state', 'not in', ('paid', 'cancel'))]
        if since_date:
            invl_search.append(('due_date', '>=', since_date))
        if to_date:
            invl_search.append(('due_date', '<=', to_date))

        return self.env['account.invoice.line'].search(invl_search)

    @api.multi
    def _filter_clean_invoices(self, since_date, to_date):
        """ Construct filter domain to be passed on method
        clean_invoices_paid, which will determine which invoice lines will
        be removed from invoices. """
        if not since_date:
            since_date = fields.Date.today()
        invl_search = [('contract_id', 'in', self.ids), ('state', '=', 'paid'),
                       ('due_date', '>=', since_date)]
        if to_date:
            invl_search.append(('due_date', '<=', to_date))
        return invl_search
