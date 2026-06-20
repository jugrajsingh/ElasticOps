import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"

export interface AuthStatus {
  setup_required: boolean
  authenticated: boolean
  user: UserInfo | null
}

export interface UserInfo {
  id: number
  email: string
  name: string
  role: string
  is_active: boolean
}

export interface UserDetail extends UserInfo {
  cluster_ids: number[]
  created_at: string
}

interface LoginRequest {
  email: string
  password: string
}

interface SetupRequest {
  name: string
  email: string
  password: string
}

interface InviteRequest {
  name: string
  email: string
  password: string
  role?: string
  cluster_ids?: number[]
}

interface TokenResponse {
  access_token: string
  token_type: string
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth", "status"],
    queryFn: () => apiFetch<AuthStatus>("/api/auth/status"),
    retry: false,
  })
}

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => apiFetch<UserInfo>("/api/auth/me"),
    retry: false,
    enabled: !!localStorage.getItem("eo_token"),
  })
}

export function useLogin() {
  return useMutation({
    mutationFn: (data: LoginRequest) =>
      apiFetch<TokenResponse>("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),
  })
}

export function useSetup() {
  return useMutation({
    mutationFn: (data: SetupRequest) =>
      apiFetch<TokenResponse>("/api/auth/setup", { method: "POST", body: JSON.stringify(data) }),
  })
}

export function useAdminUsers() {
  return useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => apiFetch<UserDetail[]>("/api/admin/users"),
    enabled: !!localStorage.getItem("eo_token"),
  })
}

export function useInviteUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: InviteRequest) =>
      apiFetch<UserDetail>("/api/admin/users", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  })
}

export function useDeleteUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: number) =>
      apiFetch(`/api/admin/users/${userId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  })
}

export function useUpdateUserClusters() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, clusterIds }: { userId: number; clusterIds: number[] }) =>
      apiFetch(`/api/admin/users/${userId}/clusters`, {
        method: "PUT",
        body: JSON.stringify(clusterIds),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  })
}
