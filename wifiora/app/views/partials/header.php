<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Painel Administrativo - Sidebar</title>

  <!-- Bootstrap 5 -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <!-- Bootstrap Icons -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css" rel="stylesheet">

  <style>
    body {
      font-family: 'Inter', sans-serif;
      background-color: #f8f9fa;
      margin: 0;
      padding-left: 250px; /* Largura da sidebar */
    }

    .sidebar {
      position: fixed;
      top: 0;
      left: 0;
      height: 100vh;
      width: 250px;
      background-color: #ffffff;
      box-shadow: 2px 0 12px rgba(0, 0, 0, 0.05);
      padding: 1rem 1rem;
      display: flex;
      flex-direction: column;
      z-index: 1030;
    }

    .sidebar .brand {
      font-size: 1.3rem;
      font-weight: 600;
      color: #14b421ff;
      margin-bottom: 2rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .sidebar .nav-link {
      color: #333;
      padding: 0.75rem 1rem;
      border-radius: 0.375rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      transition: background-color 0.2s, color 0.2s;
    }

    .sidebar .nav-link:hover,
    .sidebar .nav-link.active {
      background-color: #14b421ff;
      color: #fff;
    }

    .sidebar .nav-link i {
      font-size: 1.2rem;
    }

    .content {
      padding: 2rem;
    }

    @media (max-width: 768px) {
      body {
        padding-left: 0;
      }

      .sidebar {
        width: 100%;
        height: auto;
        position: relative;
        flex-direction: row;
        padding: 0.5rem;
        overflow-x: auto;
      }

      .sidebar .nav-link {
        flex: 1 1 auto;
        justify-content: center;
        padding: 0.5rem;
      }

      .content {
        padding: 1rem;
      }
    }
  </style>
</head>
<body>

  <aside class="sidebar">
    <div class="brand">
      <i class="bi bi-wifi"></i> Wifiora
    </div>
    <nav class="nav flex-column">
      <a class="nav-link " href="/dashboard.php">
        <i class="bi bi-speedometer2"></i> Dashboard
      </a>
      <a class="nav-link" href="/administradores.php">
        <i class="bi bi-person-badge-fill"></i> Administradores
      </a>
      <a class="nav-link" href="/visitantes.php">
        <i class="bi bi-people-fill"></i> Visitantes
      </a>
      <a class="nav-link text-danger" href="/logout.php">
        <i class="bi bi-box-arrow-right"></i> Sair
      </a>
    </nav>
  </aside>

  <main class="content">
    <h1>Bem-vindo ao Painel</h1>
    <p>Adicionar nome da empresa</p>
  </main>

  <!-- Bootstrap JS -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
