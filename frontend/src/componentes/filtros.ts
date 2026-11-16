/** Filtro e ordenação da tabela de resultados, sem React. */

import type { LinhaResultado } from "../api/tipos";

export type Filtros = {
  busca: string;
  localizacao: string | null;
  persistencia: string | null;
  soComProblema: boolean;
  soComRecomendacao: boolean;
};

export const FILTROS_VAZIOS: Filtros = {
  busca: "",
  localizacao: null,
  persistencia: null,
  soComProblema: false,
  soComRecomendacao: false,
};

export function temProblema(linha: LinhaResultado): boolean {
  return (
    linha.erros_contrato.length > 0 ||
    linha.alertas_coerencia.length > 0 ||
    Boolean(linha.erro_execucao)
  );
}

/** A persistência da linha como o filtro a enxerga ("sem" quando vazia). */
export function persistenciaDaLinha(linha: LinhaResultado): string {
  return linha.persistencia ?? "sem";
}

export function filtrarLinhas(linhas: LinhaResultado[], filtros: Filtros): LinhaResultado[] {
  const busca = filtros.busca.trim().toLocaleLowerCase("pt-BR");
  return linhas.filter((linha) => {
    if (busca) {
      const texto = [linha.enderecoid, linha.conclusao_resumo, ...linha.recomendacoes]
        .join(" ")
        .toLocaleLowerCase("pt-BR");
      if (!texto.includes(busca)) return false;
    }
    if (filtros.localizacao && (linha.localizacao ?? "SEM_RESULTADO") !== filtros.localizacao) {
      return false;
    }
    if (filtros.persistencia && persistenciaDaLinha(linha) !== filtros.persistencia) return false;
    if (filtros.soComProblema && !temProblema(linha)) return false;
    if (filtros.soComRecomendacao && linha.recomendacoes.length === 0) return false;
    return true;
  });
}

export type Coluna =
  | "enderecoid"
  | "localizacao"
  | "persistencia"
  | "diferenca_aev"
  | "recomendacoes"
  | "problemas"
  | "duracao_s";

export type Ordem = { coluna: Coluna; crescente: boolean };

function chave(linha: LinhaResultado, coluna: Coluna): string | number | null {
  switch (coluna) {
    case "recomendacoes":
      return linha.recomendacoes.length;
    case "problemas":
      return linha.erros_contrato.length + linha.alertas_coerencia.length +
        (linha.erro_execucao ? 1 : 0);
    default:
      return linha[coluna];
  }
}

/** Ordena sem mexer na lista recebida. Vazio vai sempre para o fim. */
export function ordenarLinhas(linhas: LinhaResultado[], ordem: Ordem): LinhaResultado[] {
  const sinal = ordem.crescente ? 1 : -1;
  return [...linhas].sort((a, b) => {
    const x = chave(a, ordem.coluna);
    const y = chave(b, ordem.coluna);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * sinal;
    return String(x).localeCompare(String(y), "pt-BR", { numeric: true }) * sinal;
  });
}

/** Os números da fileira de indicadores. */
export function contar(linhas: LinhaResultado[]) {
  return {
    total: linhas.length,
    encontrados: linhas.filter((l) => l.localizacao === "ENCONTRADO").length,
    gravados: linhas.filter((l) => l.persistencia === "registrado").length,
    comProblema: linhas.filter(temProblema).length,
    comRecomendacao: linhas.filter((l) => l.recomendacoes.length > 0).length,
  };
}
