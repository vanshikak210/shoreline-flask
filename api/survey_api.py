from flask import Blueprint, request, jsonify
from flask_restful import Api, Resource
from model.survey import Survey
from __init__ import app, db

survey_api = Blueprint('survey_api', __name__, url_prefix='/api/survey')
api = Api(survey_api)

class SurveyAPI:
    class _Create(Resource):
        def post(self):
            data = request.get_json()
            response = data.get('response')
            name = data.get('name')
            email = data.get('email')

            if response not in Survey.VALID_RESPONSES:
                return {"message": f"response must be one of {Survey.VALID_RESPONSES}"}, 400

            survey = Survey(response, name, email).create()
            return jsonify(survey.read())

    class _ReadAll(Resource):
        def get(self):
            surveys = Survey.query.order_by(Survey.created_at.desc()).all()
            return jsonify([s.read() for s in surveys])

    class _Stats(Resource):
        def get(self):
            counts = {choice: 0 for choice in Survey.VALID_RESPONSES}
            for choice, total in db.session.query(Survey.response, db.func.count(Survey.id)).group_by(Survey.response).all():
                if choice in counts:
                    counts[choice] = total
            return jsonify(counts)

api.add_resource(SurveyAPI._Create, '/')
api.add_resource(SurveyAPI._ReadAll, '/all')
api.add_resource(SurveyAPI._Stats, '/stats')
