import React, { useMemo, useState } from 'react';
import { User } from '../../types';
import { Role, Roles } from '../../lib/vectorStore';
import { apiUrl } from '../../lib/api';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Dialog, DialogContent } from '../ui/dialog';
import { Plus, Save, X } from 'lucide-react';

interface UserManagementProps {
  users: User[];
  onRefresh: () => void;
}

export function UserManagement({ users, onRefresh }: UserManagementProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [savingIds, setSavingIds] = useState<Record<string, boolean>>({});
  const [draftRoles, setDraftRoles] = useState<Record<string, Role>>({});
  const [createForm, setCreateForm] = useState<{ name: string; username: string; password: string; role: Role }>({
    name: '',
    username: '',
    password: '',
    role: 'Employee'
  });

  const roleLabel = (r: Role) => (r === 'SuperManager' ? 'Super Manager' : r);

  const roleBadge = (r: Role) => {
    if (r === 'SuperManager') return 'bg-purple-100 text-purple-700';
    if (r === 'Manager') return 'bg-amber-100 text-amber-800';
    if (r === 'Lead') return 'bg-emerald-100 text-emerald-800';
    return 'bg-blue-100 text-blue-700';
  };

  const usersWithDraft = useMemo(() => {
    return (users || []).map(u => ({
      ...u,
      _draftRole: (draftRoles[u.id] || u.role) as Role
    }));
  }, [users, draftRoles]);

  const createUser = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const res = await fetch(apiUrl('/admin/users'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: createForm.name,
          username: createForm.username,
          password: createForm.password,
          role: createForm.role
        })
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.message || 'Create user failed');
      setOpen(false);
      setCreateForm({ name: '', username: '', password: '', role: 'Employee' });
      await onRefresh();
    } finally {
      setCreating(false);
    }
  };

  const saveRole = async (userId: string) => {
    const nextRole = draftRoles[userId];
    if (!nextRole) return;
    if (savingIds[userId]) return;
    setSavingIds(prev => ({ ...prev, [userId]: true }));
    try {
      const res = await fetch(apiUrl(`/admin/users/${userId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: nextRole })
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.message || 'Update user failed');
      setDraftRoles(prev => {
        const n = { ...prev };
        delete n[userId];
        return n;
      });
      await onRefresh();
    } finally {
      setSavingIds(prev => ({ ...prev, [userId]: false }));
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="p-6 border-b border-neutral-100">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-neutral-900">User Management</h2>
            <p className="text-sm text-neutral-500 mt-1">Create users and manage their roles</p>
          </div>
          <Button className="h-10" onClick={() => setOpen(true)}>
            <Plus className="w-4 h-4 mr-2" />
            New User
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-6">
        <div className="bg-white border border-neutral-200 rounded-lg overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-neutral-50">
              <tr className="text-xs font-semibold text-neutral-500 uppercase tracking-wider border-b border-neutral-200">
                <th className="px-6 py-3">Name</th>
                <th className="px-6 py-3">Username</th>
                <th className="px-6 py-3">Role</th>
                <th className="px-6 py-3">Joined</th>
                <th className="px-6 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {usersWithDraft.map(u => (
                <tr key={u.id} className="text-sm hover:bg-neutral-50 transition-colors">
                  <td className="px-6 py-4 font-medium text-neutral-900">{u.name}</td>
                  <td className="px-6 py-4 text-neutral-600">{u.username}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${roleBadge(u.role)}`}>
                        {roleLabel(u.role)}
                      </span>
                      <select
                        className="h-9 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-900"
                        value={u._draftRole}
                        onChange={(e) => setDraftRoles(prev => ({ ...prev, [u.id]: e.target.value as Role }))}
                      >
                        {Roles.map(r => (
                          <option key={r} value={r}>{roleLabel(r)}</option>
                        ))}
                      </select>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-neutral-500">{new Date(u.createdAt).toLocaleDateString()}</td>
                  <td className="px-6 py-4 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-9"
                      disabled={!draftRoles[u.id] || savingIds[u.id]}
                      onClick={() => saveRole(u.id)}
                    >
                      <Save className="w-4 h-4 mr-2" />
                      Save
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-white max-w-lg">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-lg font-semibold text-neutral-900">Create User</div>
              <div className="text-sm text-neutral-500 mt-1">Create a new user and assign a role.</div>
            </div>
            <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => setOpen(false)}>
              <X className="w-5 h-5" />
            </Button>
          </div>

          <div className="mt-4 space-y-3">
            <div>
              <div className="text-xs font-semibold text-neutral-500 uppercase tracking-wider ml-1 mb-1.5">Full Name</div>
              <Input value={createForm.name} onChange={(e) => setCreateForm(prev => ({ ...prev, name: e.target.value }))} placeholder="Full name" />
            </div>
            <div>
              <div className="text-xs font-semibold text-neutral-500 uppercase tracking-wider ml-1 mb-1.5">Username</div>
              <Input value={createForm.username} onChange={(e) => setCreateForm(prev => ({ ...prev, username: e.target.value }))} placeholder="Username" />
            </div>
            <div>
              <div className="text-xs font-semibold text-neutral-500 uppercase tracking-wider ml-1 mb-1.5">Password</div>
              <Input type="password" value={createForm.password} onChange={(e) => setCreateForm(prev => ({ ...prev, password: e.target.value }))} placeholder="Password" />
            </div>
            <div>
              <div className="text-xs font-semibold text-neutral-500 uppercase tracking-wider ml-1 mb-1.5">Role</div>
              <select
                className="h-10 w-full rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-900"
                value={createForm.role}
                onChange={(e) => setCreateForm(prev => ({ ...prev, role: e.target.value as Role }))}
              >
                {Roles.map(r => (
                  <option key={r} value={r}>{roleLabel(r)}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Button variant="outline" className="h-10" onClick={() => setOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button
              className="h-10"
              onClick={createUser}
              disabled={creating || !createForm.username.trim() || !createForm.password.trim() || !createForm.name.trim()}
            >
              Create
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
