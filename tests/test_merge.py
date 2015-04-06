# -*- coding: utf-8 -*-
from __future__ import absolute_import
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User, Group, Permission
from django.core.urlresolvers import reverse
from django.test import TransactionTestCase
from django_dynamic_fixture import G
from django_webtest import WebTestMixin
import six
from adminactions.api import merge, ALL_FIELDS

from demo.common import BaseTestCaseMixin
from demo.utils import SelectRowsMixin
from demo.utils import user_grant_permission
from demo.models import UserDetail
from six.moves import range

PROFILE_MODULE = getattr(settings, 'AUTH_PROFILE_MODULE', 'tests.UserProfile')


def get_profile(user):
    return UserDetail.objects.get_or_create(user=user, note="")[0]


class MergeTestApi(BaseTestCaseMixin, TransactionTestCase):
    def setUp(self):
        super(MergeTestApi, self).setUp()
        self.master_pk = 2
        self.other_pk = 3

    def tearDown(self):
        super(MergeTestApi, self).tearDown()

    def test_merge_success_no_commit(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        result = merge(master, other)

        self.assertTrue(User.objects.filter(pk=master.pk).exists())
        self.assertTrue(User.objects.filter(pk=other.pk).exists())

        self.assertEqual(result.pk, master.pk)
        self.assertEqual(result.first_name, other.first_name)
        self.assertEqual(result.last_name, other.last_name)
        self.assertEqual(result.password, other.password)

    def test_merge_success_fields_no_commit(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        result = merge(master, other, ['password', 'last_login'])

        master = User.objects.get(pk=master.pk)

        self.assertTrue(User.objects.filter(pk=master.pk).exists())
        self.assertTrue(User.objects.filter(pk=other.pk).exists())

        self.assertNotEqual(result.last_login, master.last_login)
        self.assertEqual(result.last_login, other.last_login)
        self.assertEqual(result.password, other.password)

        self.assertNotEqual(result.last_name, other.last_name)

    def test_merge_success_commit(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        result = merge(master, other, commit=True)

        master = User.objects.get(pk=result.pk)  # reload
        self.assertTrue(User.objects.filter(pk=master.pk).exists())
        self.assertFalse(User.objects.filter(pk=other.pk).exists())

        self.assertEqual(result.pk, master.pk)
        self.assertEqual(master.first_name, other.first_name)
        self.assertEqual(master.last_name, other.last_name)
        self.assertEqual(master.password, other.password)

    def test_merge_success_m2m(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        group = Group.objects.get_or_create(name='G1')[0]
        other.groups.add(group)
        other.save()

        result = merge(master, other, commit=True, m2m=['groups'])
        master = User.objects.get(pk=result.pk)  # reload
        self.assertSequenceEqual(master.groups.all(), [group])

    def test_merge_success_m2m_all(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        group = Group.objects.get_or_create(name='G1')[0]
        perm = Permission.objects.all()[0]
        other.groups.add(group)
        other.user_permissions.add(perm)
        other.save()

        merge(master, other, commit=True, m2m=ALL_FIELDS)
        self.assertSequenceEqual(master.groups.all(), [group])
        self.assertSequenceEqual(master.user_permissions.all(), [perm])

    def test_merge_success_related_all(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        entry = other.logentry_set.get_or_create(object_repr='test', action_flag=1)[0]

        result = merge(master, other, commit=True, related=ALL_FIELDS)

        master = User.objects.get(pk=result.pk)  # reload
        self.assertSequenceEqual(master.logentry_set.all(), [entry])
        self.assertTrue(LogEntry.objects.filter(pk=entry.pk).exists())

    # @skipIf(not hasattr(settings, 'AUTH_PROFILE_MODULE'), "")
    def test_merge_one_to_one_field(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        profile = get_profile(other)
        if profile:
            entry = other.logentry_set.get_or_create(object_repr='test', action_flag=1)[0]

            result = merge(master, other, commit=True, related=ALL_FIELDS)

            master = User.objects.get(pk=result.pk)  # reload
            self.assertSequenceEqual(master.logentry_set.all(), [entry])
            self.assertTrue(LogEntry.objects.filter(pk=entry.pk).exists())
            self.assertEqual(get_profile(result), profile)
            # self.assertEqual(master.get_profile(), profile)

    def test_merge_ignore_related(self):
        master = User.objects.get(pk=self.master_pk)
        other = User.objects.get(pk=self.other_pk)
        entry = other.logentry_set.get_or_create(object_repr='test', action_flag=1)[0]
        result = merge(master, other, commit=True, related=None)

        master = User.objects.get(pk=result.pk)  # reload
        self.assertSequenceEqual(master.logentry_set.all(), [])
        self.assertFalse(User.objects.filter(pk=other.pk).exists())
        self.assertFalse(LogEntry.objects.filter(pk=entry.pk).exists())


class TestMergeAction(SelectRowsMixin, WebTestMixin, TransactionTestCase):
    fixtures = ['adminactions.json', 'demoproject.json']
    urls = 'demo.urls'
    sender_model = User
    action_name = 'merge'
    _selected_rows = [1, 2]

    def setUp(self):
        super(TestMergeAction, self).setUp()
        self.url = reverse('admin:auth_user_changelist')
        self.user = G(User, username='user', is_staff=True, is_active=True)

    def _run_action(self, steps=3, page_start=None):
        with user_grant_permission(self.user, ['auth.change_user', 'auth.adminactions_merge_user']):
            if isinstance(steps, int):
                steps = list(range(1, steps + 1))
                res = self.app.get('/', user='user')
                res = res.click('Users')
            else:
                res = page_start
            if 1 in steps:
                form = res.forms['changelist-form']
                form['action'] = 'merge'
                self._select_rows(form)
                res = form.submit()
                assert not hasattr(res.form, 'errors')

            if 2 in steps:
                res.form['username'] = res.form['form-1-username'].value
                res.form['email'] = res.form['form-1-email'].value
                res.form['last_login'] = res.form['form-1-last_login'].value
                res.form['date_joined'] = res.form['form-1-date_joined'].value
                res = res.form.submit('preview')
                assert not hasattr(res.form, 'errors')

            if 3 in steps:
                res = res.form.submit('apply')
            return res

    def test_no_permission(self):
        with user_grant_permission(self.user, ['auth.change_user']):
            res = self.app.get('/', user='user')
            res = res.click('Users')
            form = res.forms['changelist-form']
            form['action'] = 'merge'
            self._select_rows(form)
            res = form.submit().follow()
            assert six.b('Sorry you do not have rights to execute this action') in res.body

    def test_success(self):
        res = self._run_action(1)
        preserved = User.objects.get(pk=self._selected_values[0])
        removed = User.objects.get(pk=self._selected_values[1])

        assert preserved.email != removed.email  # sanity check

        res = self._run_action([2, 3], res)

        self.assertFalse(User.objects.filter(pk=removed.pk).exists())
        self.assertTrue(User.objects.filter(pk=preserved.pk).exists())

        preserved_after = User.objects.get(pk=self._selected_values[0])
        self.assertEqual(preserved_after.email, removed.email)
        self.assertFalse(LogEntry.objects.filter(pk=removed.pk).exists())

    def test_error_if_too_many_records(self):
        with user_grant_permission(self.user, ['auth.change_user', 'auth.adminactions_merge_user']):
            res = self.app.get('/', user='user')
            res = res.click('Users')
            form = res.forms['changelist-form']
            form['action'] = 'merge'
            self._select_rows(form, [1, 2, 3])
            res = form.submit().follow()
            self.assertContains(res, 'Please select exactly 2 records')

    def test_swap(self):
        with user_grant_permission(self.user, ['auth.change_user', 'auth.adminactions_merge_user']):
            # removed = User.objects.get(pk=self._selected_rows[0])
            # preserved = User.objects.get(pk=self._selected_rows[1])

            res = self.app.get('/', user='user')
            res = res.click('Users')
            form = res.forms['changelist-form']
            form['action'] = 'merge'
            self._select_rows(form, [1, 2])
            res = form.submit()
            removed = User.objects.get(pk=self._selected_values[0])
            preserved = User.objects.get(pk=self._selected_values[1])

            # steps = 2 (swap):
            res.form['master_pk'] = self._selected_values[1]
            res.form['other_pk'] = self._selected_values[0]

            res.form['username'] = res.form['form-0-username'].value
            res.form['email'] = res.form['form-0-email'].value
            res.form['last_login'] = res.form['form-1-last_login'].value
            res.form['date_joined'] = res.form['form-1-date_joined'].value

            # res.form['field_names'] = 'username,email'

            res = res.form.submit('preview')
            # steps = 3:
            res = res.form.submit('apply')

            preserved_after = User.objects.get(pk=self._selected_values[1])
            self.assertFalse(User.objects.filter(pk=removed.pk).exists())
            self.assertTrue(User.objects.filter(pk=preserved.pk).exists())

            self.assertEqual(preserved_after.email, removed.email)
            self.assertFalse(LogEntry.objects.filter(pk=removed.pk).exists())

    def test_merge_move_detail(self):
        from adminactions.merge import MergeForm

        with user_grant_permission(self.user, ['auth.change_user', 'auth.adminactions_merge_user']):
            # removed = User.objects.get(pk=self._selected_rows[0])
            # preserved = User.objects.get(pk=self._selected_rows[1])

            res = self.app.get('/', user='user')
            res = res.click('Users')
            form = res.forms['changelist-form']
            form['action'] = 'merge'
            self._select_rows(form, [1, 2])
            res = form.submit()
            removed = User.objects.get(pk=self._selected_values[0])
            preserved = User.objects.get(pk=self._selected_values[1])

            removed.userdetail_set.create(note='1')
            preserved.userdetail_set.create(note='2')

            # steps = 2:
            res.form['master_pk'] = self._selected_values[1]
            res.form['other_pk'] = self._selected_values[0]

            res.form['username'] = res.form['form-0-username'].value
            res.form['email'] = res.form['form-0-email'].value
            res.form['last_login'] = res.form['form-1-last_login'].value
            res.form['date_joined'] = res.form['form-1-date_joined'].value
            res.form['dependencies'] = MergeForm.DEP_MOVE
            res = res.form.submit('preview')
            # steps = 3:
            res = res.form.submit('apply')

            preserved_after = User.objects.get(pk=self._selected_values[1])
            self.assertEqual(preserved_after.userdetail_set.count(), 2)
            self.assertFalse(User.objects.filter(pk=removed.pk).exists())

    def test_merge_delete_detail(self):
        from adminactions.merge import MergeForm

        with user_grant_permission(self.user, ['auth.change_user', 'auth.adminactions_merge_user']):
            # removed = User.objects.get(pk=self._selected_rows[0])
            # preserved = User.objects.get(pk=self._selected_rows[1])

            res = self.app.get('/', user='user')
            res = res.click('Users')
            form = res.forms['changelist-form']
            form['action'] = 'merge'
            self._select_rows(form, [1, 2])
            res = form.submit()
            removed = User.objects.get(pk=self._selected_values[0])
            preserved = User.objects.get(pk=self._selected_values[1])

            removed.userdetail_set.create(note='1')
            preserved.userdetail_set.create(note='2')

            # steps = 2:
            res.form['master_pk'] = self._selected_values[1]
            res.form['other_pk'] = self._selected_values[0]

            res.form['username'] = res.form['form-0-username'].value
            res.form['email'] = res.form['form-0-email'].value
            res.form['last_login'] = res.form['form-1-last_login'].value
            res.form['date_joined'] = res.form['form-1-date_joined'].value
            res.form['dependencies'] = MergeForm.DEP_DELETE
            res = res.form.submit('preview')
            # steps = 3:
            res = res.form.submit('apply')

            preserved_after = User.objects.get(pk=self._selected_values[1])
            self.assertEqual(preserved_after.userdetail_set.count(), 1)
            self.assertFalse(User.objects.filter(pk=removed.pk).exists())


