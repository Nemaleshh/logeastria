from flask import Flask

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)



def create_app(config_object: str | None = None) -> Flask:
    """
    Application Factory

    Responsibilities:
    - Create Flask app instance
    - Load configuration
    - Register blueprints
    - Attach extensions (only initialization, no logic)

    NO business logic must exist here.
    """

    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    if config_object:
        app.config.from_object(config_object)
    else:
        # Default safe configuration (override via environment)
        app.config.from_mapping(
            ENV="production",
            DEBUG=False,
            TESTING=False,
        )

    # ------------------------------------------------------------------
    # Blueprint Registration
    # ------------------------------------------------------------------
    from routes.inventory_routes import inventory_bp
    from routes.production_routes import production_bp
    from routes.procurement_routes import procurement_bp
    from routes.logistics_routes import logistics_bp
    from routes.warehouse_routes import warehouse_bp
    from routes.orchestrator_routes import orchestrator_bp

    app.register_blueprint(inventory_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(procurement_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(warehouse_bp)
    app.register_blueprint(orchestrator_bp)
    
    

    # ------------------------------------------------------------------
    # Return Application Instance
    # ------------------------------------------------------------------
    return app


# ----------------------------------------------------------------------
# Application Entry Point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    application = create_app()
    # Print all registered routes for easy reference
    print("\n=== Registered Routes ===")
    for rule in sorted(application.url_map.iter_rules(), key=lambda r: r.rule):
        methods = ','.join(sorted(r for r in rule.methods if r not in ('HEAD','OPTIONS')))
        print(f"  [{methods:6}] {rule.rule}")
    print("========================\n")
    application.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
