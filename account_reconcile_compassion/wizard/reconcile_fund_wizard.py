﻿# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2014 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Cyril Sester <csester@compassion.ch>
#
#    The licence is in the file __openerp__.py
#
##############################################################################

from openerp import api, models, fields, exceptions, _


class reconcile_fund_self(models.TransientModel):
    """wizard that helps the user doing a full reconciliation when a customer
    paid more than excepted. It puts the extra amount in a fund selected
    in the self and fully reconcile the credit line. """
    _name = 'reconcile.fund.wizard'

    fund_id = fields.Many2one(
        'product.product', 'Fund', required=True,
        default=lambda self: self._get_general_fund())
    contract_ids = fields.Many2many(
        'recurring.contract',
        string='Related contracts',
        default=lambda self: self._get_contract_ids())

    def _get_contract_ids(self):
        move_line_obj = self.env['account.move.line']
        contract_ids = False
        active_ids = self.env.context.get('active_ids')
        if active_ids:
            contract_ids = move_line_obj.browse(active_ids).filtered(
                lambda mvl: mvl.debit > 0).mapped(
                'invoice.invoice_line.contract_id.id') or False
        return contract_ids

    def _write_contracts(self):
        return True

    def _get_general_fund(self):
        general_fund = self.env['product.product'].search(
            [('name', '=', 'General Fund')], limit=1)
        return general_fund.id

    @api.multi
    def reconcile_with_fund(self):
        ''' Generate an invoice corresponding to the selected fund
            and reconcile it with selected move lines
        '''
        if not self.contract_ids:
            raise exceptions.Warning(
                _('No contract'),
                _('This operation is only allowed for invoices related to '
                  'sponsorships.'))
        active_ids = self.env.context.get('active_ids')
        invoice = False
        move_line_obj = self.env['account.move.line']
        residual = 0.0

        for line in move_line_obj.browse(active_ids):
            residual += line.credit - line.debit
            if not invoice and line.debit > 0:
                invoice = line.invoice
                account_id = line.invoice.account_id.id
                partner_id = line.partner_id.id
                active_ids.remove(line.id)

        if residual <= 0:
            raise exceptions.Warning(
                'ResidualError',
                _('This can only be done if credits > debits'))

        if invoice:
            invoice.action_cancel()
            invoice.action_cancel_draft()

            self._generate_invoice_line(invoice.id, residual, partner_id)

            # Validate the invoice
            invoice.signal_workflow('invoice_open')
            move_lines = move_line_obj.search([
                ('move_id', '=', invoice.move_id.id),
                ('account_id', '=', account_id)])
            move_lines |= move_line_obj.browse(active_ids)
            move_lines.reconcile('manual')

        return {'type': 'ir.actions.act_window_close'}

    def _generate_invoice_line(self, invoice_id, price, partner_id):
        product = self.fund_id
        inv_line_data = {
            'name': product.name,
            'account_id': product.property_account_income.id,
            'price_unit': price / len(self.contract_ids),
            'quantity': 1,
            'uos_id': False,
            'product_id': product.id or False,
            'invoice_id': invoice_id,
        }

        # Define analytic journal
        analytic = self.env['account.analytic.default'].account_get(
            product.id, partner_id)
        if analytic and analytic.analytic_id:
            inv_line_data['account_analytic_id'] = analytic.analytic_id.id

        for contract_id in self.contract_ids.ids:
            inv_line_data['contract_id'] = contract_id
            self.env['account.invoice.line'].create(
                inv_line_data)

        return True
