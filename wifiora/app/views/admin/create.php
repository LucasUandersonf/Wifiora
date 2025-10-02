<?php require __DIR__ . '/../partials/header.php'; ?>





<div class="container my-5">
    <h2 class="mb-4">Novo Administrador</h2>

    <?php if (isset($error)) echo "<div class='alert alert-danger'>" . htmlspecialchars($error) . "</div>"; ?>

    <form method="POST" action="">
        <div class="mb-3">
            <label class="form-label">Email:</label>
            <input type="email" name="email" class="form-control" required>
        </div>

        <div class="mb-3">
            <label class="form-label">Senha:</label>
            <input type="password" name="password" class="form-control" required>
        </div>

        <button type="submit" class="btn btn-success">Criar</button>
        <a href="/administradores.php" class="btn btn-secondary ms-2">Cancelar</a>
    </form>
</div>

<?php require __DIR__ . '/../partials/footer.php'; ?>
