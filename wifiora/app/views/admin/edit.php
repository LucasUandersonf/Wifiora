<?php require __DIR__ . '/../partials/header.php'; ?>

<div class="container my-5">
    <h2 class="mb-4">Editar Administrador</h2>

    <?php if (isset($error)): ?>
        <div class="alert alert-danger"><?= htmlspecialchars($error) ?></div>
    <?php endif; ?>

    <form method="POST" action="/edit_admin" class="needs-validation" novalidate>
        <input type="hidden" name="id" value="<?= htmlspecialchars($admin['id']) ?>">

        <div class="mb-3">
            <label for="email" class="form-label">Email:</label>
            <input 
                type="email" 
                class="form-control" 
                id="email" 
                name="email" 
                value="<?= htmlspecialchars($admin['email']) ?>" 
                required>
        </div>

        <div class="mb-3">
            <label for="password" class="form-label">Nova Senha (opcional):</label>
            <input 
                type="password" 
                class="form-control" 
                id="password" 
                name="password">
        </div>

        <button type="submit" class="btn btn-success">Salvar Alterações</button>
        <a href="/administradores.php" class="btn btn-secondary ms-2">Cancelar</a>
    </form>
</div>

<?php require __DIR__ . '/../partials/footer.php'; ?>
