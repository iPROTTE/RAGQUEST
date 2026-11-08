# Ragquest - Agentes de conhecimento locais

O Ragquest é uma estrutura de agentes de IA que roda no servidor da própria empresa, sem custo por uso. Cada agente atende uma área do negócio (ex.: Operações FTTH, Comercial, Engenharia Elétrica) e responde com base nos documentos da sua pasta: manuais, diretrizes e POPs. A conversa é natural, o Ragquest se lembra de cada usuário e aprende uma "skill" para cada documento novo.

## Instalação (servidor da empresa)

1. Baixe o **Ragquest-Instalador** mais recente em **Releases** (lado direito desta página).
2. Execute o .exe. Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações** → **Executar assim mesmo**.
3. Escolha **"Servidor da empresa"** para os funcionários acessarem pela rede (computador e celular). O Windows pede permissão para liberar o firewall: clique em **Sim**.
4. Na primeira abertura, o Ragquest baixa os modelos de IA (3 a 6 GB) e pede a **chave de licença**.
5. Crie a conta de **administrador**.

## Agentes

- Na aba **Agentes**, o administrador cria um agente por área (nome, ícone, descrição e instruções).
- Cada agente tem a sua pasta em **Documentos\Ragquest - Conhecimento\<Nome do agente>** (subpastas pop, manual, diretriz, outros). Só ele usa esse conhecimento.
- As pastas pop, manual, diretriz e outros da raiz formam a **base geral**, que o agente pode consultar se o administrador permitir.
- Perguntas fora da área do agente: ele avisa que não tem esse conhecimento e oferece pesquisar na internet, sem incorporar o resultado.
- Na aba **Usuários**, o administrador define quais agentes cada funcionário pode usar.

## Acesso dos funcionários

- **Computador:** abrir no navegador o endereço mostrado em Usuários → Acesso dos funcionários.
- **Android:** ler o QR code, tocar em **Baixar o app** e depois em **Abrir no app** (ou instalar o **Ragquest-Android.apk** desta página).
- **iPhone:** ler o QR code e, no Safari, **Compartilhar → Adicionar à Tela de Início**.

Cada funcionário entra com o próprio login e senha. Conversas ficam salvas por agente, e o que o usuário conta sobre si pode ser visto e apagado em **Meu perfil**. O número de usuários e de agentes é definido na licença.

## Requisitos do servidor

- Windows 10 ou 11, 64 bits
- 16 GB de RAM recomendado (funciona com 8 GB usando o modelo leve)
- 10 GB livres em disco
- Placa NVIDIA recomendada para respostas mais rápidas

A chave de licença é enviada individualmente. Não compartilhe.

## App Android

O código do app está na pasta `android` e é compilado automaticamente pelo GitHub Actions. A assinatura do APK é feita fora do GitHub.
