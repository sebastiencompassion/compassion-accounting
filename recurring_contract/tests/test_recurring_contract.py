# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2015-2017 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Albert SHENOUDA <albert.shenouda@efrei.net>, Emanuel Cino
#
#    The licence is in the file __openerp__.py
#
##############################################################################

from openerp import fields
from openerp.tests.common import TransactionCase
import logging
import random
import string
logger = logging.getLogger(__name__)


class BaseContractTest(TransactionCase):
    def setUp(self):
        super(BaseContractTest, self).setUp()
        self.thomas = self.env.ref('base.res_partner_address_3')
        self.michel = self.env.ref('base.res_partner_address_4')
        self.david = self.env.ref('base.res_partner_address_10')
        self.group_obj = self.env['recurring.contract.group'].with_context(
            async_mode=False)
        self.con_obj = self.env['recurring.contract'].with_context(
            async_mode=False)
        self.payment_term = self.env.ref(
            'account.account_payment_term_immediate')
        self.product = self.env.ref('product.product_product_35')
        # Make all journals cancellable
        self.env['account.journal'].search([]).write({'update_posted': True})

    def ref(self, length):
        return ''.join(random.choice(string.lowercase) for i in range(length))


class TestRecurringContract(BaseContractTest):
    """
        Test Project recurring contract.
        We are testing the three scenarios :
        The first one :
            - we are creating one contract
            - a payment option in which:
                - 1 invoice is generated every month
                - with 1 month of invoice generation in advance
        We are testing if invoices data are coherent with data in the
        associate contract.
        The second scenario is created to test the fusion of invoices when two
        contracts are present in same group.
        The third scenario consists in the creation of several contracts with
        several line, then we are testing that the invoices are good updated
        when we cancel one contract.
    """
    def test_generated_invoice(self):
        """
            Test the button_generate_invoices method which call a lot of
            other methods like generate_invoice(). We are testing the coherence
            of data when a contract generate invoice(s).
        """
        # Creation of a group and a contracts with one line
        group = self.group_obj.create({
            'advance_billing_months': 1,
            'payment_term_id': self.payment_term.id,
            'change_method': 'do_nothing',
            'recurring_value': 1,
            'recurring_unit': 'month',
            'partner_id': self.michel.id
        })
        contract = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 40.0,
                'quantity': 1
            })]
        })

        # Creation of data to test
        original_product = self.product.name
        original_partner = self.michel.name
        original_price = contract.total_amount
        original_start_date = contract.start_date

        # To generate invoices, the contract must be "active"
        contract.signal_workflow('contract_validated')
        self.assertEqual(contract.state, 'active')
        invoicer_id = contract.button_generate_invoices()
        invoices = invoicer_id.invoice_ids
        nb_invoice = len(invoices)
        # 2 invoices must be generated with our parameters
        self.assertEqual(nb_invoice, 2)
        invoice = invoices[1]
        self.assertEqual(original_product, invoice.invoice_line_ids[0].name)
        self.assertEqual(original_partner, invoice.partner_id['name'])
        self.assertEqual(original_price, invoice.amount_untaxed)
        self.assertEqual(original_start_date, invoice.date_invoice)

        contract.signal_workflow('contract_terminated')
        self.assertEqual(contract.state, 'terminated')

        original_total = contract.total_amount
        self.assertEqual(original_total, invoice.amount_total)

    def test_generated_invoice_second_scenario(self):
        """
            Creation of the second contract to test the fusion of invoices if
            the partner and the dates are the same. Then there is the test of
            the changement of the payment option and its consequences : check
            if all data of invoices generated are correct, and if the number
            of invoices generated is correct
        """
        # Creation of a group and two contracts with one line each
        group = self.group_obj.create({
            'advance_billing_months': 1,
            'payment_term_id': self.payment_term.id,
            'change_method': 'do_nothing',
            'recurring_value': 1,
            'recurring_unit': 'month',
            'partner_id': self.michel.id
        })
        contract = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 75.0,
                'quantity': 1
            })]
        })
        contract2 = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 85.0,
                'quantity': 1
            })]
        })

        original_price1 = contract.total_amount
        original_price2 = contract2.total_amount

        # We put the contracts in active state to generate invoices
        contract.signal_workflow('contract_validated')
        contract2.signal_workflow('contract_validated')
        self.assertEqual(contract2.state, 'active')
        invoicer_obj = self.env['recurring.invoicer']
        invoicer_id = contract2.button_generate_invoices()
        invoices = invoicer_id.invoice_ids
        nb_invoice = len(invoices)
        self.assertEqual(nb_invoice, 2)
        invoice_fus = invoices[-1]
        self.assertEqual(
            original_price1 + original_price2, invoice_fus.amount_untaxed)

        # Changement of the payment option
        group.write(
            {
                'change_method': 'clean_invoices',
                'recurring_value': 2,
                'recurring_unit': 'week',
                'advance_billing_months': 2,
            })
        new_invoicer_id = invoicer_obj.search([], order='id DESC')[0]
        new_invoices = new_invoicer_id.invoice_ids
        nb_new_invoices = len(new_invoices)
        self.assertEqual(nb_new_invoices, 5)

        # Copy of one contract to test copy method()
        contract_copied = contract2.copy()
        self.assertTrue(contract_copied.id)
        contract_copied.signal_workflow('contract_validated')
        self.assertEqual(contract_copied.state, 'active')
        contract_copied_line = contract_copied.contract_line_ids[0]
        contract_copied_line.write({'amount': 160.0})
        new_price2 = contract_copied_line.subtotal
        invoicer_id = self.env[
            'recurring.invoicer.wizard'].generate().get('res_id')
        invoicer_wiz = self.env['recurring.invoicer'].browse(invoicer_id)
        new_invoices = invoicer_wiz.invoice_ids
        new_invoice_fus = new_invoices[-1]
        self.assertEqual(new_price2, new_invoice_fus.amount_untaxed)

    def test_generated_invoice_third_scenario(self):
        """
            Creation of several contracts of the same group to test the case
            if we cancel one of the contracts if invoices are still correct.
        """
        group = self.group_obj.create({
            'advance_billing_months': 1,
            'payment_term_id': self.payment_term.id,
            'change_method': 'do_nothing',
            'recurring_value': 1,
            'recurring_unit': 'month',
            'partner_id': self.michel.id
        })
        contract = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 10.0,
                'quantity': 1
            }), (0, 0, {
                'product_id': self.product.id,
                'amount': 20.0,
                'quantity': 1
            })]
        })
        contract2 = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 30.0,
                'quantity': 1
            }), (0, 0, {
                'product_id': self.product.id,
                'amount': 40.0,
                'quantity': 1
            })]
        })
        contract3 = self.con_obj.create({
            'reference': self.ref(10),
            'start_date': fields.Date.today(),
            'next_invoice_date': fields.Date.today(),
            'partner_id': self.michel.id,
            'group_id': group.id,
            'state': 'draft',
            'contract_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'amount': 15.0,
                'quantity': 1
            }), (0, 0, {
                'product_id': self.product.id,
                'amount': 25.0,
                'quantity': 1
            })]
        })

        # Creation of data to test
        original_product = self.product.name
        original_partner = self.michel.name
        original_price = sum((contract + contract2 + contract3).mapped(
            'total_amount'))
        original_start_date = contract.start_date

        # We put all the contracts in active state
        contract.signal_workflow('contract_validated')
        contract2.signal_workflow('contract_validated')
        contract3.signal_workflow('contract_validated')
        # Creation of a wizard to generate invoices
        invoicer_id = self.env[
            'recurring.invoicer.wizard'].generate().get('res_id')
        invoicer = self.env['recurring.invoicer'].browse(invoicer_id)
        invoices = invoicer.invoice_ids
        invoice = invoices[0]
        invoice2 = invoices[1]

        # We put the third contract in terminate state to see if
        # the invoice is well updated
        date_finish = fields.Datetime.now()
        contract3.signal_workflow('contract_terminated')
        # Check a job for cleaning invoices has been created
        self.assertTrue(self.env['queue.job'].search([
            ('name', '=', 'Job for cleaning invoices of contracts.'),
            ('date_created', '>=', date_finish)]))
        # Force cleaning invoices immediatley
        contract3._clean_invoices()
        self.assertEqual(contract3.state, 'terminated')
        self.assertEqual(original_product, invoice.invoice_line_ids[0].name)
        self.assertEqual(original_partner, invoice.partner_id['name'])
        self.assertEqual(
            original_price - contract3.total_amount,
            invoice.amount_total)
        self.assertEqual(original_start_date, invoice2.date_invoice)
