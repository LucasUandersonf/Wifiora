<?php 
require __DIR__ . '/../partials/header.php'; 

require_once __DIR__ . '/../../models/Visitor.php';

// Instancia a classe Visitor
$visitorModel = new Visitor();

// Captura o parâmetro de busca, se existir
$search = $_GET['search'] ?? null;

// Faz a consulta (retorna mysqli_result ou false)
$visitors = $visitorModel->getAll($search);

// Caso a query falhe, inicialize $visitors para evitar erros na view
if (!$visitors) {
    $visitors = new class {
        public $num_rows = 0;
        public function fetch_assoc() { return null; }
    };
}
?>

<div class="container py-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="mb-0">Visitantes</h2>
        <a href="/export_csv.php" class="btn btn-success" style="background-color: #14b421ff; border-color: #14b421ff;">Exportar CSV</a>
    </div>

    <form method="GET" action="" class="row g-3 mb-4">
        <div class="col-sm-10">
            <input type="text" name="search" class="form-control" placeholder="Buscar por nome, CPF, email..." value="<?= htmlspecialchars($search) ?>">
        </div>
        <div class="col-sm-2 d-grid">
            <button type="submit" class="btn btn-primary" style="background-color: #14b421ff; border-color: #14b421ff;">Buscar</button>
        </div>
    </form>

    <div class="table-responsive">
        <table class="table table-striped table-hover align-middle">
            <thead class="table-dark">
                <tr>
                    <th>Nome</th>
                    <th>CPF</th>
                    <th>Email</th>
                    <th>Tipo</th>
                    <th>Ações</th>
                </tr>
            </thead>
            <tbody>
                <?php if ($visitors->num_rows > 0): ?>
                    <?php while ($row = $visitors->fetch_assoc()): ?>
                    <tr>
                        <td><?= htmlspecialchars($row['name']) ?></td>
                        <td><?= htmlspecialchars($row['cpf']) ?></td>
                        <td><?= htmlspecialchars($row['email']) ?></td>
                        <td><?= htmlspecialchars($row['user_type']) ?></td>
                        <td>
                            <a href="/editar_visitantes.php?id=<?= $row['id'] ?>" class="btn btn-sm btn-warning">Editar</a>
                            <a href="/delete_visitor.php?id=<?= $row['id'] ?>" class="btn btn-sm btn-danger" onclick="return confirm('Deseja excluir?')">Excluir</a>
                        </td>
                    </tr>
                    <?php endwhile; ?>
                <?php else: ?>
                    <tr>
                        <td colspan="5" class="text-center">Nenhum visitante encontrado</td>
                    </tr>
                <?php endif; ?>
            </tbody>
        </table>
    </div>
</div>

<?php require __DIR__ . '/../partials/footer.php'; ?>
