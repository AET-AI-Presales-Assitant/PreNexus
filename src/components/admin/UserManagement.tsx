import React from 'react';
import { User } from '../../types';

interface UserManagementProps {
  users: User[];
}

export function UserManagement({ users }: UserManagementProps) {
  return (
    <div className="flex flex-col h-full bg-white">
      <div className="p-6 border-b border-neutral-100">
        <h2 className="text-xl font-bold text-neutral-900">User Management</h2>
        <p className="text-sm text-neutral-500 mt-1">Manage registered users and their roles</p>
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
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {users.map(u => (
                <tr key={u.id} className="text-sm hover:bg-neutral-50 transition-colors">
                  <td className="px-6 py-4 font-medium text-neutral-900">{u.name}</td>
                  <td className="px-6 py-4 text-neutral-600">{u.username}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${u.role === 'Admin' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-neutral-500">{new Date(u.createdAt).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
