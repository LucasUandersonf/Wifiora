<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Painel Administrativo - Login</title>

  <!-- Bootstrap 5 -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">

  <!-- Bootstrap Icons -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css" rel="stylesheet">

  <!-- Google Fonts: Inter (moderno e clean) -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">

  <style>
    :root {
      --bg-color: #f1f4f9;
      --card-bg: #ffffff;
      --primary-color: #4f46e5;
      --text-color: #1f2937;
    }

    * {
      box-sizing: border-box;
    }

    body {
      background-color: var(--bg-color);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-color);
    }

    .login-card {
      background-color: var(--card-bg);
      padding: 2.5rem;
      border-radius: 1rem;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
      width: 100%;
      max-width: 420px;
      animation: fadeIn 0.6s ease;
    }

    @keyframes fadeIn {
      from {
        opacity: 0;
        transform: translateY(20px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .login-card h4 {
      font-weight: 600;
    }

    .form-label {
      font-weight: 500;
    }

    .form-control {
      padding-left: 2.5rem;
    }

    .input-icon {
      position: relative;
    }

    .input-icon i {
      position: absolute;
      top: 50%;
      left: 0.75rem;
      transform: translateY(-50%);
      color: #6b7280;
    }

    .btn-primary {
      background-color: var(--primary-color);
      border: none;
      font-weight: 500;
      transition: all 0.3s ease;
    }

    .btn-primary:hover {
      background-color: #4338ca;
      box-shadow: 0 4px 12px rgba(79, 70, 229, 0.2);
    }

    .text-muted small {
      font-size: 0.85rem;
    }

    @media (max-width: 480px) {
      .login-card {
        padding: 2rem 1.5rem;
      }
    }
  </style>
</head>
<body>

  <div class="login-card">
    <h4 class="mb-1 text-center">Painel Administrativo</h4>
    <p class="text-center text-muted mb-4"><small>Wifiora</small></p>


    <form method="POST" action="/login.php">
      <div class="mb-3 input-icon">
        <label for="email" class="form-label">Email</label>
        <i class="bi bi-envelope-fill"></i>
        <input type="email" class="form-control" id="email" name="email" required placeholder="seuemail@exemplo.com">
      </div>

      <div class="mb-4 input-icon">
        <label for="password" class="form-label">Senha</label>
        <i class="bi bi-lock-fill"></i>
        <input type="password" class="form-control" id="password" name="password" required placeholder="••••••••">
      </div>

      <button type="submit" class="btn btn-primary w-100">Entrar</button>
    </form>
  </div>

  <!-- Bootstrap Bundle (JS) -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
