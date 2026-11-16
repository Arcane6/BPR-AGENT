/** As consultas e ações da tela, sobre o React Query. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./cliente";
import type {
  Acao,
  Ambiente,
  Consumo,
  Conversa,
  DetalheEndereco,
  Escopo,
  LinhaResultado,
  Lote,
  LoteNaLista,
  Saude,
  SituacaoLote,
} from "./tipos";

/** Situações em que o lote ainda muda sozinho e a tela consulta de novo. */
export const SITUACOES_VIVAS: SituacaoLote[] = ["em_andamento", "parando"];

export function useSaude() {
  return useQuery({
    queryKey: ["saude"],
    queryFn: () => api.get<Saude>("/api/saude"),
    refetchInterval: 5000,
  });
}

export function useAcoes() {
  return useQuery({
    queryKey: ["acoes"],
    queryFn: async () => (await api.get<{ acoes: Acao[] }>("/api/acoes")).acoes,
    staleTime: Infinity,
  });
}

export function useEscopo(acoes: string[], permitirExtracao: boolean) {
  return useQuery({
    queryKey: ["escopo", acoes, permitirExtracao],
    queryFn: () => api.post<Escopo>("/api/escopo", { acoes, permitir_extracao: permitirExtracao }),
    retry: false,
  });
}

export function useAmbiente(permitirExtracao: boolean) {
  return useQuery({
    queryKey: ["ambiente", permitirExtracao],
    queryFn: () => api.get<Ambiente>(`/api/ambiente?permitir_extracao=${permitirExtracao}`),
  });
}

export function useLotes() {
  return useQuery({
    queryKey: ["lotes"],
    queryFn: async () => (await api.get<{ lotes: LoteNaLista[] }>("/api/lotes")).lotes,
    refetchInterval: (consulta) =>
      consulta.state.data?.some((l) => SITUACOES_VIVAS.includes(l.situacao)) ? 2000 : false,
  });
}

export function useLote(loteId: string) {
  return useQuery({
    queryKey: ["lote", loteId],
    queryFn: () => api.get<Lote>(`/api/lotes/${loteId}`),
    refetchInterval: (consulta) =>
      consulta.state.data && SITUACOES_VIVAS.includes(consulta.state.data.situacao) ? 2000 : false,
  });
}

export function useDetalheEndereco(loteId: string | null, executionId: string | null) {
  return useQuery({
    queryKey: ["endereco", loteId, executionId],
    queryFn: () =>
      api.get<DetalheEndereco>(`/api/lotes/${loteId}/enderecos/${executionId}`),
    enabled: Boolean(loteId && executionId),
  });
}

export function useConsumo(mes: string | null) {
  return useQuery({
    queryKey: ["consumo", mes],
    queryFn: () => api.get<Consumo>(mes ? `/api/consumo?mes=${mes}` : "/api/consumo"),
    refetchInterval: 30000,
  });
}

export function useResultados() {
  return useQuery({
    queryKey: ["resultados"],
    queryFn: async () =>
      (await api.get<{ linhas: LinhaResultado[] }>("/api/resultados")).linhas,
  });
}

export type PedidoLote = {
  enderecos: string[];
  acoes: string[];
  permitir_extracao: boolean;
  concorrencia: number;
  pular_gravados: boolean;
};

export function useIniciarLote() {
  const cliente = useQueryClient();
  return useMutation({
    mutationFn: (pedido: PedidoLote) => api.post<{ lote_id: string }>("/api/lotes", pedido),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: ["lotes"] });
      void cliente.invalidateQueries({ queryKey: ["saude"] });
    },
  });
}

export function usePararLote(loteId: string) {
  const cliente = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ situacao: string }>(`/api/lotes/${loteId}/parar`),
    onSuccess: () => void cliente.invalidateQueries({ queryKey: ["lote", loteId] }),
  });
}

export function useLerArquivoEnderecos() {
  return useMutation({
    mutationFn: (arquivo: File) =>
      api.enviarArquivo<{ enderecos: string[]; repetidos: string[] }>(
        "/api/enderecos/arquivo",
        arquivo,
      ),
  });
}

export function useConversa(sessaoId: string | null) {
  return useQuery({
    queryKey: ["conversa", sessaoId],
    queryFn: () => api.get<Conversa>(`/api/conversas/${sessaoId}`),
    enabled: Boolean(sessaoId),
    refetchInterval: (consulta) => (consulta.state.data?.ocupada ? 1000 : false),
    retry: false,
  });
}

export function useNovaConversa() {
  return useMutation({ mutationFn: () => api.post<Conversa>("/api/conversas") });
}

export function useEnviarMensagem(sessaoId: string | null) {
  const cliente = useQueryClient();
  return useMutation({
    mutationFn: (texto: string) =>
      api.post<Conversa>(`/api/conversas/${sessaoId}/mensagens`, { texto }),
    onSuccess: (conversa) => cliente.setQueryData(["conversa", sessaoId], conversa),
  });
}
